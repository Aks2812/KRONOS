FROM python:3.12-slim
RUN pip install --no-cache-dir awscli
WORKDIR /app
COPY cloud/init_localstack.sh /app/init_localstack.sh
RUN chmod +x /app/init_localstack.sh
CMD ["/app/init_localstack.sh"]
