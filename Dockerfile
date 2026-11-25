FROM mcr.microsoft.com/playwright/python:v1.57.0-noble
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \
    apt-get update && apt-get install -y --no-install-recommends xvfb x11vnc novnc websockify supervisor && \
    rm -rf /var/lib/apt/lists/*
COPY . .
ENV DISPLAY=:99 PYTHONUNBUFFERED=1
EXPOSE 8501 6080
CMD ["supervisord", "-n", "-c", "/app/supervisord.conf"]
