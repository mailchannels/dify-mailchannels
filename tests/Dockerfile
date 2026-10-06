FROM python:3.12-slim
WORKDIR /src
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt pytest responses
COPY . .
CMD ["python", "tests/runtime_check.py", "/package.difypkg"]
