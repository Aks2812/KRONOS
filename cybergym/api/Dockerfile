FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY api/app.py /app/cybergym_api_app.py
EXPOSE 8091
CMD ["uvicorn", "cybergym_api_app:app", "--host", "0.0.0.0", "--port", "8091"]
