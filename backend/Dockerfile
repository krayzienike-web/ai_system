FROM python:3.12-slim
RUN pip install --no-cache-dir uv==0.8.17
WORKDIR /app
ENV UV_PROJECT_ENVIRONMENT=/opt/venv PATH="/opt/venv/bin:$PATH"
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY . .
# Not root: a hole in the API gives the container's user, nothing more (pre-pilot review 10.11.2026, p. 21)
RUN useradd --system --uid 10001 --no-create-home app
USER app
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
