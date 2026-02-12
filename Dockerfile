FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY meischtergruen.py .
CMD ["python", "-u", "meischtergruen.py"]
