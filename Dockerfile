# Use official Python image
FROM python:3.10.3

# Set the working directory in the container
WORKDIR /app

# Copy project files
COPY . /app/

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Set environment variables (Adjust as needed)
ENV PYTHONUNBUFFERED=1 \
    PORT=8080 \
    DJANGO_SETTINGS_MODULE=speech_to_text_web_app.settings
    

# Collect static files (avoid interactive prompts)
RUN python manage.py collectstatic --noinput

# Expose port for Gunicorn
EXPOSE 8080

# Start Gunicorn server with 3 workers and 4 threads
CMD ["gunicorn", "-k", "gevent", "--bind", "0.0.0.0:8080", "speech_to_text_web_app.wsgi"]
