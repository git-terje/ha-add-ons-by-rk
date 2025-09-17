ARG BUILD_FROM=ghcr.io/home-assistant/aarch64-base:latest
FROM ${BUILD_FROM}
RUN apk add --no-cache python3 py3-pip py3-cryptography git build-base
WORKDIR /app
RUN python3 -m venv /venv
ENV PATH="/venv/bin:$PATH"
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY run.py .
COPY static ./static
EXPOSE 8091
CMD ["python","run.py"]
