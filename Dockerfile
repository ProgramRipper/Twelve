FROM python:slim AS base
WORKDIR /app
ENV PATH=.venv/bin:${PATH}


FROM base AS build
ENV PDM_CHECK_UPDATE=false

RUN pip install --no-cache-dir pdm
RUN --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=pdm.lock,target=pdm.lock \
    --mount=type=cache,target=/root/.cache/pdm \
    pdm sync --prod --no-editable


FROM base

COPY --link --from=build /app/.venv/ .venv
COPY --link . .

CMD nb orm upgrade && nb run
