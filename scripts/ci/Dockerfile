FROM maven:3.9.9-eclipse-temurin-21 AS java
FROM node:20-bookworm-slim AS node
FROM mongo:7.0.16 AS mongo
FROM mcr.microsoft.com/dotnet/sdk:10.0.201-noble

ENV JAVA_HOME=/opt/java/openjdk \
    MAVEN_HOME=/usr/share/maven \
    MONGODB_TEST_BINARY=/usr/local/bin/mongod \
    JAVA_TEST_BINARY=/opt/java/openjdk/bin/java \
    CHROME_BIN=/usr/bin/google-chrome \
    DOTNET_CLI_TELEMETRY_OPTOUT=1 \
    DOTNET_NOLOGO=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CI=true
ENV PATH="/opt/java/openjdk/bin:/usr/share/maven/bin:${PATH}"
COPY --from=java /opt/java/openjdk /opt/java/openjdk
COPY --from=java /usr/share/maven /usr/share/maven
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
COPY --from=mongo /usr/bin/mongod /usr/local/bin/mongod
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
    && apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-venv curl ca-certificates libcurl4t64 libssl3t64 \
    && curl --fail --location --retry 3 https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb -o /tmp/chrome.deb \
    && apt-get install -y --no-install-recommends /tmp/chrome.deb \
    && rm -f /tmp/chrome.deb \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /work
COPY . /work
RUN mkdir -p /work/reports \
    && for component in services/cargas-python services/transportista-simulator mongo; do \
         python3 -m venv "$component/.venv"; \
         "$component/.venv/bin/python" -m pip install --no-cache-dir -r "$component/requirements.txt" || exit 1; \
       done
ENTRYPOINT ["bash", "/work/scripts/ci/in-container.sh"]
