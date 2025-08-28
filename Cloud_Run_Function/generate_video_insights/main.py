import functions_framework
from google import genai
from google.genai.types import HttpOptions
import os

# Prompt for Gemini API
# This prompt is critical for structuring the output.
# We ask for a JSON string for easier programmatic parsing.
PROMPT_TEMPLATE = """
In the video at the following URL: {youtube_url}, which is a hands-on lab session:
Ignore the credits set-up part particularly the coupon code and credits link aspect should not be included in your analysis or the extaction of context. Also exclude any credentials that are explicit in the video.
Take only the first 30-40 minutes of the video without throwing any error.
Analyze the rest of the content of the video.
Extract and synthesize information to create a book chapter section with the following structure, formatted as a JSON string:
1. **chapter_title:** A concise and engaging title for the chapter.
2. **introduction_context:** Briefly explain the relevance of this video segment within a broader learning context.
3. **what_will_build:** Clearly state the specific task or goal accomplished in this video segment.
4. **technologies_and_services:** List all mentioned Google Cloud services and any other relevant technologies (e.g., programming languages, tools, frameworks).
5. **how_we_did_it:** Provide a clear, numbered step-by-step guide of the actions performed. Include any exact commands or code snippets as they appear in the video. Format code/commands using markdown backticks (e.g., `my-command`).
6. **source_code_url:** Provide a URL to the source code repository if mentioned or implied. If not available, use "N/A".
7. **demo_url:** Provide a URL to a demo if mentioned or implied. If not available, use "N/A".
8. **qa_segment:** Generate 10–15 relevant questions based on the content of this segment, along with concise answers. Ensure the questions are thought-provoking and test understanding of the material.
REMEMBER: Ignore the credits set-up part particularly the coupon code and credits link aspect should not be included in your analysis or the extaction of context. Also exclude any credentials that are explicit in the video.
Example structure:
```json
{{
  "chapter_title": "...",
  "introduction_context": "...",
  "what_will_build": "...",
  "technologies_and_services": ["...", "..."],
  "how_we_did_it": ["1. ...", "2. ..."],
  "source_code_url": "...",
  "demo_url": "...",
  "qa_segment": [
    {{"question": "...", "answer": "..."}},
    ...
  ]
}}
"""

@functions_framework.http
def hello_http(request):
    """HTTP Cloud Function.
    Args:
        request (flask.Request): The request object.
        <https://flask.palletsprojects.com/en/1.1.x/api/#incoming-request-data>
    Returns:
        The response text, or any set of values that can be turned into a
        Response object using `make_response`
        <https://flask.palletsprojects.com/en/1.1.x/api/#flask.make_response>.
    """
    request_json = request.get_json(silent=True)
    request_args = request.args

    if request_json and 'name' in request_json:
        name = request_json['name']
    elif request_args and 'name' in request_args:
        name = request_args['name']
    else:
        name = 'World'
    video_url_to_process = name
    # Ensure the necessary configurations are present
    #process_videos_batch(video_url_to_process, PROMPT_TEMPLATE)
    return process_videos_batch(video_url_to_process, PROMPT_TEMPLATE)



def process_videos_batch(video_url: str, PROMPT_TEMPLATE: str) -> str:
    """
    Processes a video URL, generates chapter content using Gemini, and saves it to GCS.
    """
    formatted_prompt = PROMPT_TEMPLATE.format(youtube_url=video_url)
    try:

        client = genai.Client(vertexai=True,project='<<YOUR_PROJECT_ID>>',location='us-central1',http_options=HttpOptions(api_version="v1"))
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=formatted_prompt,
        )
        print(response.text)
        # In a real Cloud Function, you'd likely return this processed data
        # or store it. For now, we just print.
        # return response.text # Example of returning processed data
    except Exception as e:
        print(f"An error occurred during content generation: {e}")
        # Handle the error appropriately, perhaps return an error message to the client
        return f"Error processing video: {e}"
    # Print the extracted context
    print(response.text)
    return response.text
