ARG BUILD_FROM=ghcr.io/home-assistant/aarch64-base:latest
FROM ${BUILD_FROM}
RUN apk add --no-cache python3 py3-pip git
WORKDIR /app
COPY run.py /app/run.py
CMD ["python3","/app/run.py"]
