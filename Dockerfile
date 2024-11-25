FROM python:slim
WORKDIR /app
ENV PATH=.venv/bin:${PATH}

RUN pip install pdm && pip cache purge
COPY pyproject.toml pdm.lock ./
RUN pdm sync -G docker --prod --no-editable && \
    pdm cache clear && \
    \
    pip freeze | xargs pip uninstall -y && \
    \
    playwright install chromium --with-deps && \
    apt clean && \
    rm -rf /var/lib/apt/lists/*
COPY . .

CMD nb orm upgrade && nb run
