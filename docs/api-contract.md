# HopTrace API Contract

Base path: /api/v1

## Network
GET /health
GET /topology
POST /lab/run

## Incidents
GET /incidents/latest
GET /incidents/{id}
GET /incidents/{id}/affected-subscribers
POST /incidents/{id}/explain

## Subscribers
GET /subscribers
POST /subscribers/{id}/remind

## Responsibilities

- The network engine owns fault localization.
- Neo4j stores network topology and relationships.
- The backend exposes the documented API endpoints.
- The frontend consumes API responses rather than hardcoding
  final diagnoses or subscriber counts.
- The Sarvam integration explains verified application results.
- Test scenarios must keep the injected fault separate from
  the diagnostic prediction.
