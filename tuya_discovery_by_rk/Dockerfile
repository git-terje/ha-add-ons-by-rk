ARG BUILD_FROM=ghcr.io/home-assistant/aarch64-base:latest
FROM ${BUILD_FROM}
RUN apk add --no-cache python3 py3-pip git
WORKDIR /app
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt
COPY run.py .
EXPOSE 8097
CMD ["python3","/app/run.py"]
