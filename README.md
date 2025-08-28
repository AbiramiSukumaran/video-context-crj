# video-context-crj
Converting Code Vipassana Session videos into book chapters using Cloud Run Jobs, BigQuery and of course Gemini!

1. Deploy the video insights Cloud Run Functions first.
2. Then, build your Python application (start with a simple project folder with main.py, requirements.txt and Dockerfile in it)
3. Or you can just clone this repo (and delete the Cloud Run Functions folder)
4. Provide the appropriate env variables' values
5. Containerize and create a Cloud Run Job:
   How? Refer to this blog: 
