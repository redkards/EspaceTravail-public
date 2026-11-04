FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 SERENITY_DATA=/data
COPY app /app
USER 65534:65534
EXPOSE 8100
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8100/sante',timeout=4).status==200 else 1)"
CMD ["python", "/app/serenity.py"]
