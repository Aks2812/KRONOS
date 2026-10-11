FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY cloud/ /app/cybergym/cloud/
RUN touch /app/cybergym/__init__.py
ENV PYTHONPATH=/app
EXPOSE 4567
CMD ["uvicorn", "cybergym.cloud.sigv4_proxy:app", "--host", "0.0.0.0", "--port", "4567"]
