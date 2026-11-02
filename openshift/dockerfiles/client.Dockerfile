FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/tmp \
    XDG_CACHE_HOME=/tmp/.cache \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

WORKDIR /app

COPY client/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY client /app/client
COPY shared /app/shared

RUN chmod -R g=u /app /tmp

EXPOSE 8501

CMD ["streamlit", "run", "client/app.py", "--server.port=8501", "--server.address=0.0.0.0"]
