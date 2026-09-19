FROM mcr.microsoft.com/dotnet/sdk:10.0.201-noble AS build
WORKDIR /src
COPY Directory.Build.props NuGet.Config ./
COPY src/Despachos.Api/Despachos.Api.csproj src/Despachos.Api/
COPY src/Despachos.Application/Despachos.Application.csproj src/Despachos.Application/
COPY src/Despachos.Domain/Despachos.Domain.csproj src/Despachos.Domain/
COPY src/Despachos.Infrastructure/Despachos.Infrastructure.csproj src/Despachos.Infrastructure/
RUN dotnet restore src/Despachos.Api/Despachos.Api.csproj
COPY src/ ./src/
RUN dotnet publish src/Despachos.Api/Despachos.Api.csproj -c Release --no-restore -o /out /p:UseAppHost=false

FROM mcr.microsoft.com/dotnet/aspnet:10.0.5-noble
USER root
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=build /out/ ./
ENV ASPNETCORE_URLS=http://+:8091
USER app
EXPOSE 8091
ENTRYPOINT ["dotnet", "Despachos.Api.dll"]
