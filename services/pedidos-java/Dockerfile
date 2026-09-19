FROM maven:3.9.9-eclipse-temurin-21 AS build
WORKDIR /src
COPY pom.xml ./
COPY src/main ./src/main
RUN mvn -B -ntp package -Dmaven.test.skip=true

FROM eclipse-temurin:21.0.10_7-jre-jammy
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 app && useradd --uid 10001 --gid app --create-home app
WORKDIR /app
COPY --from=build /src/target/pedidos-1.0.0.jar ./pedidos.jar
COPY --chown=app:app keys/reto-private.pem keys/reto-public.pem ./keys/
RUN chmod 600 keys/reto-private.pem
USER app
EXPOSE 8090
ENTRYPOINT ["java", "-jar", "/app/pedidos.jar"]
