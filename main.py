
from google.cloud import bigquery
from google.cloud.exceptions import NotFound
import os
import logging
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError, Future
import requests # For calling your existing Cloud Run service
import json

# --- Configuration ---
# MANDATORY: Set these as environment variables for your Cloud Run Job
BIGQUERY_PROJECT = os.environ.get("BIGQUERY_PROJECT")
BIGQUERY_DATASET = os.environ.get("BIGQUERY_DATASET")
BIGQUERY_TABLE_SOURCE = os.environ.get("BIGQUERY_TABLE_SOURCE") # Table with URLs
BIGQUERY_TABLE_TARGET = os.environ.get("BIGQUERY_TABLE_TARGET") 

# !!! IMPORTANT !!! Replace this with your endpoint
# The URL of your *existing* Cloud Run service that processes single URLs.
URL_PROCESSOR_SERVICE_URL = os.environ.get("URL_PROCESSOR_SERVICE_URL", "https://python-video-context-YOUR_PROJECT_NUMBER.us-central1.run.app")

# --- Initialize Clients ---
try:
    bq_client = bigquery.Client(project=BIGQUERY_PROJECT)
    logging.info("BigQuery client initialized successfully.")
except Exception as e:
    logging.error(f"Failed to initialize BigQuery client: {e}")
    raise

if not URL_PROCESSOR_SERVICE_URL:
    logging.error("URL_PROCESSOR_SERVICE_URL is not set. Cannot proceed.")
    raise ValueError("URL_PROCESSOR_SERVICE_URL must be set.")


# --- Your Function to Call Another Service ---
def call_url_processor_service(url: str) -> str:
    """
    Calls the external Cloud Run service to process a single URL.
    Returns the text response from the service.
    """
    try:
        # Construct the payload for the request to your URL_PROCESSOR_SERVICE
        # Your service expects a JSON payload with 'name' or 'url' to process.
        # Let's assume 'name' is used to pass the URL.
        payload = {"name": url}

        headers = {'Content-Type': 'application/json'}

        # Make the HTTP request to your deployed Cloud Run service
        logging.info(f"Calling URL processor for: {url}")
        response = requests.post(
            URL_PROCESSOR_SERVICE_URL,
            json=payload,
            headers=headers,
            timeout=600 # Set a reasonable timeout for the external service call
        )
        response.raise_for_status() # Raise an exception for bad status codes (4xx or 5xx)
        
        # Assuming your URL processor service returns the text directly in response.text
        return response.text

    except requests.exceptions.Timeout:
        logging.error(f"Timeout calling URL processor for {url}.")
        return f"ERROR: Timeout processing '{url}' at {URL_PROCESSOR_SERVICE_URL}"
    except requests.exceptions.RequestException as e:
        logging.error(f"Request error calling URL processor for {url}: {e}")
        return f"ERROR: Request failed for '{url}'. Details: {e}"
    except Exception as e:
        logging.error(f"An unexpected error occurred calling URL processor for {url}: {e}")
        return f"ERROR: Unexpected error for '{url}'. Details: {e}"


# --- Helper to update a single row in BigQuery ---
def update_bq_row(row_id, context, status="COMPLETED"):
    """Updates a specific row in the target BigQuery table."""
    if not BIGQUERY_TABLE_TARGET:
        logging.error("BIGQUERY_TABLE_TARGET not configured. Cannot update BigQuery.")
        return False

    update_query = f"""
        UPDATE `{BIGQUERY_PROJECT}.{BIGQUERY_DATASET}.{BIGQUERY_TABLE_TARGET}`
        SET
            context = @context,
            status = @status
        WHERE id = @row_id
    """

    job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("context", "STRING", value=context),
                bigquery.ScalarQueryParameter("status", "STRING", value=status),
                bigquery.ScalarQueryParameter("row_id", "STRING", value=row_id)
                ]
        )

    try:
        update_job = bq_client.query(update_query, job_config=job_config)
        update_job.result() # Wait for the job to complete
        logging.info(f"Successfully updated BigQuery row ID {row_id} with status {status}.")
        return True
    except Exception as e:
        logging.error(f"Failed to update BigQuery row ID {row_id}: {e}")
        return False

# --- Main orchestrator for the Cloud Run Job ---
def process_batch_from_bq(request_or_trigger_data=None):
    """
    Cloud Run Job main function to read from BigQuery, call external service in parallel, and write back.
    """
    if not BIGQUERY_TABLE_SOURCE:
        logging.error("BIGQUERY_TABLE_SOURCE not configured. Exiting.")
        return "Configuration error: BIGQUERY_TABLE_SOURCE is not set.", 500
    if not URL_PROCESSOR_SERVICE_URL:
        logging.error("URL_PROCESSOR_SERVICE_URL is not set. Exiting.")
        return "Configuration error: URL_PROCESSOR_SERVICE_URL is not set.", 500

    # --- Configuration for Batching and Concurrency ---
    BATCH_SIZE = 5 # How many URLs to fetch from BQ per query in the job instance
    MAX_CONCURRENT_TASKS_PER_INSTANCE = 5 # How many parallel calls to the URL_PROCESSOR_SERVICE from one job instance
    URL_PROCESSOR_TIMEOUT_SECONDS = 600 # Timeout for each call to your URL processor service

    # --- Step 1: Fetch batch of URLs from BigQuery ---
    query = f"""
        SELECT url, id
        FROM `{BIGQUERY_PROJECT}.{BIGQUERY_DATASET}.{BIGQUERY_TABLE_SOURCE}`
        WHERE status = 'PENDING'
        LIMIT {BATCH_SIZE}
    """
    job_config = bigquery.QueryJobConfig()
    print(BATCH_SIZE)
    try:
        logging.info(f"Fetching up to {BATCH_SIZE} pending URLs from BigQuery...")
        rows = bq_client.query(query, job_config=job_config).result()
        
        pending_urls_data = []
        for row in rows:
            pending_urls_data.append({"url": row.url, "id": row.id})
        
        if not pending_urls_data:
            logging.info("No pending URLs found. Job finished.")
            return "No pending URLs found. Job finished.", 200

        logging.info(f"Fetched {len(pending_urls_data)} URLs for processing.")
        

        row_ids_to_process = [item["id"] for item in pending_urls_data]

        # --- Step 2: Mark URLs as PROCESSING in BigQuery ---
        update_status_query = f"""
            UPDATE `{BIGQUERY_PROJECT}.{BIGQUERY_DATASET}.{BIGQUERY_TABLE_SOURCE}`
            SET status = 'PROCESSING'
            WHERE id IN UNNEST(@row_ids_to_process)
        """
        
        status_update_job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ArrayQueryParameter("row_ids_to_process", "STRING", values=row_ids_to_process)]
        )

        
        update_status_job = bq_client.query(update_status_query, job_config=status_update_job_config)
        update_status_job.result()
        logging.info(f"Marked {len(row_ids_to_process)} URLs as 'PROCESSING'.")

        # --- Step 3: Call the external URL Processor Service in parallel ---
        processed_results = {} # Store results by row_id: {"context": str, "status": str}
        futures = []

        with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_TASKS_PER_INSTANCE) as executor:
            for item in pending_urls_data:
                url = item["url"]
                row_id = item["id"]
                # Submit the task to call the external service
                future = executor.submit(call_url_processor_service, url)
                futures.append((row_id, future))

            # Process completed futures as they finish
            for row_id, future in futures:
                try:
                    content = future.result(timeout=URL_PROCESSOR_TIMEOUT_SECONDS)
                    # Check if the result itself indicates an error from the processor
                    if content.startswith("ERROR:"):
                        processed_results[row_id] = {"context": content, "status": "FAILED_PROCESSING"}
                    else:
                        processed_results[row_id] = {"context": content, "status": "COMPLETED"}
                except TimeoutError:
                    logging.warning(f"URL processing timed out (service call for row ID {row_id}). Marking as FAILED.")
                    processed_results[row_id] = {"context": f"ERROR: Processing timed out for '{row_id}'.", "status": "FAILED_PROCESSING"}
                except Exception as e:
                    logging.error(f"Exception during future result retrieval for row ID {row_id}: {e}")
                    processed_results[row_id] = {"context": f"ERROR: Unexpected error during result retrieval for '{row_id}'. Details: {e}", "status": "FAILED_PROCESSING"}

        # --- Step 4: Write results back to BigQuery ---
        logging.info(f"Writing {len(processed_results)} results back to BigQuery...")
        successful_updates = 0
        for row_id, data in processed_results.items():
            if update_bq_row(row_id, data["context"], data["status"]):
                successful_updates += 1
        
        logging.info(f"Finished processing. {successful_updates} out of {len(processed_results)} rows updated successfully.")

        return f"Batch processing complete. Processed {len(processed_results)} URLs, updated {successful_updates}.", 200

    except NotFound:
        logging.info("Source table not found.")
        return "Source table not found.", 404
    except Exception as e:
        logging.error(f"An unhandled error occurred in the job: {e}")
        # Raise exception for Cloud Run Jobs to handle retries if configured
        raise

process_batch_from_bq()
