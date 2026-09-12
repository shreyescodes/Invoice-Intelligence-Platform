// Infra as code — phase 6.
targetScope = 'resourceGroup'

param location string = resourceGroup().location
param environmentName string = 'dev'

var suffix = uniqueString(resourceGroup().id)

var storageAccountName = 'stinv${environmentName}${suffix}'
var cosmosAccountName = 'cosmos-inv-${environmentName}-${suffix}'
var functionAppName = 'func-inv-${environmentName}-${suffix}'
var appInsightsName = 'appi-inv-${environmentName}-${suffix}'
var keyVaultName = 'kv-inv-${environmentName}-${suffix}'
var logAnalyticsWorkspaceName = 'log-inv-${environmentName}-${suffix}'
var appServicePlanName = 'asp-inv-${environmentName}-${suffix}'
var webAppName = 'api-inv-${environmentName}-${suffix}'
var staticWebAppName = 'ui-inv-${environmentName}-${suffix}'
var docIntelligenceName = 'docintel-inv-${environmentName}-${suffix}'

// Storage Account
resource storageAccount 'Microsoft.Storage/storageAccounts@2023-01-01' = {
  name: storageAccountName
  location: location
  sku: {
    name: 'Standard_LRS'
  }
  kind: 'StorageV2'
  properties: {
    minimumTlsVersion: 'TLS1_2'
  }
}

// Blob Storage Services
resource blobServices 'Microsoft.Storage/storageAccounts/blobServices@2023-01-01' = {
  name: 'default'
  parent: storageAccount
}

// Raw Invoices Container
resource rawInvoicesContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-01-01' = {
  name: 'raw-invoices'
  parent: blobServices
}

// Azure AI Document Intelligence (Form Recognizer)
resource docIntelligence 'Microsoft.CognitiveServices/accounts@2023-05-01' = {
  name: docIntelligenceName
  location: location
  kind: 'FormRecognizer'
  sku: {
    name: 'S0'
  }
  properties: {
    publicNetworkAccess: 'Enabled'
    networkAcls: {
      defaultAction: 'Allow'
    }
  }
}

// Log Analytics
resource logAnalyticsWorkspace 'Microsoft.OperationalInsights/workspaces@2022-10-01' = {
  name: logAnalyticsWorkspaceName
  location: location
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: 30
  }
}

// Application Insights
resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: appInsightsName
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logAnalyticsWorkspace.id
  }
}

// Cosmos DB
resource cosmosDbAccount 'Microsoft.DocumentDB/databaseAccounts@2024-05-15' = {
  name: cosmosAccountName
  location: location
  properties: {
    databaseAccountOfferType: 'Standard'
    locations: [
      {
        locationName: location
        failoverPriority: 0
      }
    ]
  }
}

// Cosmos DB Database
resource cosmosDbDatabase 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2024-05-15' = {
  name: 'invoice_platform'
  parent: cosmosDbAccount
  properties: {
    resource: {
      id: 'invoice_platform'
    }
  }
}

// Cosmos DB Container
resource cosmosDbContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-05-15' = {
  name: 'invoices'
  parent: cosmosDbDatabase
  properties: {
    resource: {
      id: 'invoices'
      partitionKey: {
        paths: [
          '/vendor_id'
        ]
        kind: 'Hash'
      }
    }
    options: {
      throughput: 400
    }
  }
}

// Key Vault
resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: keyVaultName
  location: location
  properties: {
    sku: {
      family: 'A'
      name: 'standard'
    }
    tenantId: subscription().tenantId
    accessPolicies: []
    enableRbacAuthorization: true
  }
}

// Function App
resource functionApp 'Microsoft.Web/sites@2023-12-01' = {
  name: functionAppName
  location: location
  kind: 'functionapp,linux'
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    siteConfig: {
      appSettings: [
        {
          name: 'AzureWebJobsStorage__accountName'
          value: storageAccount.name
        }
        {
          name: 'APPINSIGHTS_INSTRUMENTATIONKEY'
          value: appInsights.properties.InstrumentationKey
        }
        {
          name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
          value: appInsights.properties.ConnectionString
        }
        {
          name: 'FUNCTIONS_EXTENSION_VERSION'
          value: '~4'
        }
        {
          name: 'FUNCTIONS_WORKER_RUNTIME'
          value: 'python'
        }
        {
          name: 'KEY_VAULT_URL'
          value: keyVault.properties.vaultUri
        }
        {
          name: 'DOCUMENT_INTELLIGENCE_ENDPOINT'
          value: docIntelligence.properties.endpoint
        }
        {
          name: 'COSMOS_ENDPOINT'
          value: cosmosDbAccount.properties.documentEndpoint
        }
        {
          name: 'AZURE_STORAGE_CONNECTION_STRING'
          value: 'https://${storageAccount.name}.blob.core.windows.net'
        }
      ]
      linuxFxVersion: 'Python|3.11'
    }
  }
}

// App Service Plan (Linux)
resource appServicePlan 'Microsoft.Web/serverfarms@2022-09-01' = {
  name: appServicePlanName
  location: location
  sku: {
    name: 'B1'
  }
  kind: 'linux'
  properties: {
    reserved: true
  }
}

// Web App (FastAPI Backend)
resource webApp 'Microsoft.Web/sites@2022-09-01' = {
  name: webAppName
  location: location
  kind: 'app,linux'
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    serverFarmId: appServicePlan.id
    siteConfig: {
      linuxFxVersion: 'PYTHON|3.11'
      appSettings: [
        {
          name: 'APPINSIGHTS_INSTRUMENTATIONKEY'
          value: appInsights.properties.InstrumentationKey
        }
        {
          name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
          value: appInsights.properties.ConnectionString
        }
        {
          name: 'ENVIRONMENT'
          value: environmentName
        }
        {
          name: 'KEY_VAULT_URL'
          value: keyVault.properties.vaultUri
        }
        {
          name: 'DOCUMENT_INTELLIGENCE_ENDPOINT'
          value: docIntelligence.properties.endpoint
        }
        {
          name: 'COSMOS_ENDPOINT'
          value: cosmosDbAccount.properties.documentEndpoint
        }
        {
          name: 'AZURE_STORAGE_CONNECTION_STRING'
          value: 'https://${storageAccount.name}.blob.core.windows.net'
        }
      ]
    }
  }
}

// Static Web App (React Frontend)
resource staticWebApp 'Microsoft.Web/staticSites@2022-09-01' = {
  name: staticWebAppName
  location: location
  sku: {
    name: 'Free'
    tier: 'Free'
  }
  properties: {}
}

output functionAppId string = functionApp.id
output functionAppPrincipalId string = functionApp.identity.principalId
output webAppId string = webApp.id
output webAppPrincipalId string = webApp.identity.principalId
output webAppHostName string = webApp.properties.defaultHostName
output cosmosDbEndpoint string = cosmosDbAccount.properties.documentEndpoint
output docIntelligenceEndpoint string = docIntelligence.properties.endpoint
output keyVaultUri string = keyVault.properties.vaultUri

// Key Vault Secrets — seed placeholder secrets that operators must replace
// with real values before the first production deployment.
// Snowflake credentials: set these via 'az keyvault secret set' after first deploy.
resource secretSnowflakeAccount 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  name: 'snowflake-account'
  parent: keyVault
  properties: {
    value: 'REPLACE_WITH_SNOWFLAKE_ACCOUNT'
  }
}

resource secretSnowflakeUser 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  name: 'snowflake-user'
  parent: keyVault
  properties: {
    value: 'REPLACE_WITH_SNOWFLAKE_USER'
  }
}

resource secretSnowflakePassword 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  name: 'snowflake-password'
  parent: keyVault
  properties: {
    value: 'REPLACE_WITH_SNOWFLAKE_PASSWORD'
  }
}

resource secretDocIntelKey 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  name: 'document-intelligence-key'
  parent: keyVault
  properties: {
    value: listKeys(docIntelligence.id, '2023-05-01').key1
  }
}

// --- Role Assignments for Managed Identity ---

var storageBlobDataContributorRole = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'ba92f5b4-2d11-453d-a403-e96b0029c9fe')
var storageTableDataContributorRole = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '0a9a7e1f-b9d0-4cc4-a60d-0319b160aaa3')
var storageQueueDataContributorRole = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '974c5e8b-45b9-4653-ba55-5f855dd0fb88')
var keyVaultSecretsUserRole = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '4633458b-17de-408a-b874-0445c86b69e6')
var cosmosDbDataContributorRole = '00000000-0000-0000-0000-000000000002'

resource storageRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storageAccount.id, functionApp.id, storageBlobDataContributorRole)
  scope: storageAccount
  properties: {
    roleDefinitionId: storageBlobDataContributorRole
    principalId: functionApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

resource storageTableRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storageAccount.id, functionApp.id, storageTableDataContributorRole)
  scope: storageAccount
  properties: {
    roleDefinitionId: storageTableDataContributorRole
    principalId: functionApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

resource storageQueueRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storageAccount.id, functionApp.id, storageQueueDataContributorRole)
  scope: storageAccount
  properties: {
    roleDefinitionId: storageQueueDataContributorRole
    principalId: functionApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

resource keyVaultRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(keyVault.id, functionApp.id, keyVaultSecretsUserRole)
  scope: keyVault
  properties: {
    roleDefinitionId: keyVaultSecretsUserRole
    principalId: functionApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

resource cosmosRoleAssignment 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2023-04-15' = {
  name: guid(cosmosDbAccount.id, functionApp.id, cosmosDbDataContributorRole)
  parent: cosmosDbAccount
  properties: {
    roleDefinitionId: resourceId('Microsoft.DocumentDB/databaseAccounts/sqlRoleDefinitions', cosmosDbAccount.name, cosmosDbDataContributorRole)
    principalId: functionApp.identity.principalId
    scope: cosmosDbAccount.id
  }
}

// --- Role Assignments for API Web App Managed Identity ---

resource webAppStorageRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storageAccount.id, webApp.id, storageBlobDataContributorRole)
  scope: storageAccount
  properties: {
    roleDefinitionId: storageBlobDataContributorRole
    principalId: webApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

resource webAppKeyVaultRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(keyVault.id, webApp.id, keyVaultSecretsUserRole)
  scope: keyVault
  properties: {
    roleDefinitionId: keyVaultSecretsUserRole
    principalId: webApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

resource webAppCosmosRoleAssignment 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2023-04-15' = {
  name: guid(cosmosDbAccount.id, webApp.id, cosmosDbDataContributorRole)
  parent: cosmosDbAccount
  properties: {
    roleDefinitionId: resourceId('Microsoft.DocumentDB/databaseAccounts/sqlRoleDefinitions', cosmosDbAccount.name, cosmosDbDataContributorRole)
    principalId: webApp.identity.principalId
    scope: cosmosDbAccount.id
  }
}
