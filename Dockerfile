FROM python:slim as base
WORKDIR /app
ENV PLAYWRIGHT_BROWSERS_PATH=downloads/ms-playwright


FROM base as build

RUN pip install pdm
COPY pyproject.toml pdm.lock ./
RUN pdm sync --prod --no-editable && \
    pdm run playwright install chromium


FROM base

RUN pip install nb-cli
COPY --from=build /app .
RUN .venv/bin/playwright install-deps chromium && \
    apt clean && \
    rm -rf /var/lib/apt/lists/*
COPY . .

CMD nb orm upgrade && nb run
