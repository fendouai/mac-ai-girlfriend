# CPU 联调容器；不包含 CUDA、克隆音色或视频口型模型。
FROM python:3.11-slim
WORKDIR /app
RUN pip install --no-cache-dir fastapi 'uvicorn[standard]' httpx pyyaml 'numpy<2' \
    && pip install --no-cache-dir torch==2.5.1 --index-url https://download.pytorch.org/whl/cpu
COPY src ./src
COPY web ./web
COPY models/silero-vad ./models/silero-vad
COPY persona.md config.docker.yaml ./
EXPOSE 7860
CMD ["python", "src/server.py", "--config", "config.docker.yaml"]
