FROM python:slim as base
WORKDIR /app
ENV PATH=.venv/bin:${PATH}


FROM base AS build
ENV PDM_CHECK_UPDATE=false

RUN pip install pdm
COPY pyproject.toml pdm.lock ./
RUN pdm sync --prod --no-editable


FROM base

COPY --from=build /app/.venv/ .venv
COPY . .

CMD nb orm upgrade && nb run
