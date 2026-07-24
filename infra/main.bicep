// Infra as code — phase 6. Deliberately not filled in yet: writing
// this yourself against real docs is most of the learning value for
// the "cloud-native on Azure" line item. Rough shape to build toward:
//
// - Storage Account (Blob Storage, container: raw-invoices)
// - Cosmos DB account (free tier: 1000 RU/s + 25GB) with the
//   invoices + audit-log containers
// - Function App (Consumption plan) with a system-assigned Managed
//   Identity
// - Key Vault, with an access policy / RBAC role assignment granting
//   the Function App's Managed Identity "Key Vault Secrets User"
// - Document Intelligence account (F0 free tier)
// - Application Insights + Log Analytics workspace
//
// Reference: Microsoft Learn's Bicep documentation has a working
// example for each resource type above — start from those rather
// than guessing the schema.

targetScope = 'resourceGroup'

param location string = resourceGroup().location
param environmentName string = 'dev'

// TODO: resource declarations go here.
