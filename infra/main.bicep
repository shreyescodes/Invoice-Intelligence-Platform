// Invoice Intelligence Platform on Azure Container Apps.
//
//   web (nginx, public)  ->  api (internal)  ->  PostgreSQL Flexible Server
//                            worker (no ingress, scales on demand)  -> Blob Storage, ERP
//   migrate (Container Apps job, run by the deploy workflow)
//
// One user-assigned managed identity pulls images, reads Key Vault secrets and writes blobs, so no
// storage keys or registry passwords exist anywhere. Deploy infra/registry.bicep first.
targetScope = 'resourceGroup'

@description('Short environment name used in resource names: lowercase letters and digits, e.g. prod.')
@minLength(2)
@maxLength(8)
param environmentName string

param location string = resourceGroup().location

@description('Image tag (git SHA) pushed to the registry by CI.')
param imageTag string

@secure()
param postgresAdminPassword string

@secure()
@minLength(32)
param jwtSecret string

@description('Base URL of the SAP S/4HANA (or compatible) API. Empty deploys the bundled mock ERP.')
param erpBaseUrl string = ''

@secure()
param erpApiKey string = newGuid()

@description('Expose demo accounts on the login page. Only for showcase environments.')
param demoMode bool = false

@description('Optional Azure OpenAI endpoint for the natural-language analytics page.')
param azureOpenAiEndpoint string = ''
param azureOpenAiDeployment string = 'gpt-4o-mini'

var suffix = uniqueString(resourceGroup().id, environmentName)
var deployMockErp = empty(erpBaseUrl)
var tags = { application: 'invoice-intelligence', environment: environmentName }
var postgresAdmin = 'iipadmin'

var roles = {
  acrPull: '7f951dda-4ed3-4680-a7ca-43fe172d538d'
  keyVaultSecretsUser: '4633458b-17de-408a-b874-0445c86b69e6'
  storageBlobDataContributor: 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
}

// --- Identity, registry, secrets ------------------------------------------------------------------

resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-iip-${environmentName}'
  location: location
  tags: tags
}

resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' existing = {
  name: 'acriip${environmentName}${suffix}'
}

resource acrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(registry.id, identity.id, roles.acrPull)
  scope: registry
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.acrPull)
  }
}

resource vault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: 'kv-iip-${environmentName}-${take(suffix, 8)}'
  location: location
  tags: tags
  properties: {
    tenantId: subscription().tenantId
    sku: { family: 'A', name: 'standard' }
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 30
    enablePurgeProtection: true
  }
}

resource vaultSecretsUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(vault.id, identity.id, roles.keyVaultSecretsUser)
  scope: vault
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.keyVaultSecretsUser)
  }
}

var databaseUrl = 'postgresql+psycopg://${postgresAdmin}:${uriComponent(postgresAdminPassword)}@${postgres.properties.fullyQualifiedDomainName}:5432/iip?sslmode=require'

resource secretDatabaseUrl 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: vault
  name: 'database-url'
  properties: { value: databaseUrl }
}

resource secretJwt 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: vault
  name: 'jwt-secret'
  properties: { value: jwtSecret }
}

resource secretErpKey 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: vault
  name: 'erp-api-key'
  properties: { value: erpApiKey }
}

// --- Data -----------------------------------------------------------------------------------------

resource postgres 'Microsoft.DBforPostgreSQL/flexibleServers@2024-08-01' = {
  name: 'psql-iip-${environmentName}-${suffix}'
  location: location
  tags: tags
  sku: { name: 'Standard_B1ms', tier: 'Burstable' }
  properties: {
    version: '16'
    administratorLogin: postgresAdmin
    administratorLoginPassword: postgresAdminPassword
    storage: { storageSizeGB: 32, autoGrow: 'Enabled' }
    backup: { backupRetentionDays: 14, geoRedundantBackup: 'Disabled' }
    highAvailability: { mode: 'Disabled' }
    network: { publicNetworkAccess: 'Enabled' }
  }
}

resource postgresDatabase 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2024-08-01' = {
  parent: postgres
  name: 'iip'
  properties: { charset: 'UTF8', collation: 'en_US.utf8' }
}

// Container Apps egress comes from Azure-owned addresses; tighten with VNet integration for production.
resource postgresAllowAzure 'Microsoft.DBforPostgreSQL/flexibleServers/firewallRules@2024-08-01' = {
  parent: postgres
  name: 'AllowAzureServices'
  properties: { startIpAddress: '0.0.0.0', endIpAddress: '0.0.0.0' }
}

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: take('stiip${environmentName}${suffix}', 24)
  location: location
  tags: tags
  sku: { name: 'Standard_ZRS' }
  kind: 'StorageV2'
  properties: {
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storage
  name: 'default'
  properties: {
    deleteRetentionPolicy: { enabled: true, days: 30 }
    containerDeleteRetentionPolicy: { enabled: true, days: 30 }
    isVersioningEnabled: true
  }
}

resource invoicesContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: 'invoices'
  properties: { publicAccess: 'None' }
}

resource blobContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storage.id, identity.id, roles.storageBlobDataContributor)
  scope: storage
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.storageBlobDataContributor)
  }
}

// --- Container Apps -------------------------------------------------------------------------------

resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: 'log-iip-${environmentName}'
  location: location
  tags: tags
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
  }
}

resource appEnvironment 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: 'cae-iip-${environmentName}'
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logs.properties.customerId
        sharedKey: logs.listKeys().primarySharedKey
      }
    }
    workloadProfiles: [{ name: 'Consumption', workloadProfileType: 'Consumption' }]
  }
}

var image = '${registry.properties.loginServer}/invoice-intelligence'
var registries = [{ server: registry.properties.loginServer, identity: identity.id }]
var vaultSecrets = [
  { name: 'database-url', keyVaultUrl: secretDatabaseUrl.properties.secretUri, identity: identity.id }
  { name: 'jwt-secret', keyVaultUrl: secretJwt.properties.secretUri, identity: identity.id }
  { name: 'erp-api-key', keyVaultUrl: secretErpKey.properties.secretUri, identity: identity.id }
]
var erpUrl = deployMockErp ? 'https://${erpMock!.properties.configuration.ingress.fqdn}' : erpBaseUrl
var backendEnv = concat(
  [
    { name: 'ENVIRONMENT', value: demoMode ? 'development' : 'production' }
    { name: 'DEMO_MODE', value: string(demoMode) }
    { name: 'LOG_FORMAT', value: 'json' }
    { name: 'DATABASE_URL', secretRef: 'database-url' }
    { name: 'JWT_SECRET', secretRef: 'jwt-secret' }
    { name: 'ERP_API_KEY', secretRef: 'erp-api-key' }
    { name: 'ERP_BASE_URL', value: erpUrl }
    { name: 'STORAGE_BACKEND', value: 'azure_blob' }
    { name: 'AZURE_STORAGE_ACCOUNT_URL', value: storage.properties.primaryEndpoints.blob }
    { name: 'AZURE_STORAGE_CONTAINER', value: invoicesContainer.name }
    { name: 'AZURE_CLIENT_ID', value: identity.properties.clientId } // selects the identity for DefaultAzureCredential
    { name: 'MODEL_DIR', value: '/tmp/models' }
  ],
  empty(azureOpenAiEndpoint)
    ? []
    : [
        { name: 'LLM_PROVIDER', value: 'azure_openai' }
        { name: 'AZURE_OPENAI_ENDPOINT', value: azureOpenAiEndpoint }
        { name: 'LLM_MODEL', value: azureOpenAiDeployment }
      ]
)
var appIdentity = {
  type: 'UserAssigned'
  userAssignedIdentities: { '${identity.id}': {} }
}

resource erpMock 'Microsoft.App/containerApps@2024-03-01' = if (deployMockErp) {
  name: 'ca-iip-erp-${environmentName}'
  location: location
  tags: tags
  identity: appIdentity
  dependsOn: [acrPull, vaultSecretsUser]
  properties: {
    environmentId: appEnvironment.id
    workloadProfileName: 'Consumption'
    configuration: {
      ingress: { external: false, targetPort: 8100, transport: 'auto' }
      registries: registries
      secrets: vaultSecrets
    }
    template: {
      containers: [
        {
          name: 'erp-mock'
          image: '${image}/erp-mock:${imageTag}'
          resources: { cpu: json('0.25'), memory: '0.5Gi' }
          env: [{ name: 'ERP_API_KEY', secretRef: 'erp-api-key' }]
        }
      ]
      scale: { minReplicas: 1, maxReplicas: 1 }
    }
  }
}

resource api 'Microsoft.App/containerApps@2024-03-01' = {
  name: 'ca-iip-api-${environmentName}'
  location: location
  tags: tags
  identity: appIdentity
  dependsOn: [acrPull, vaultSecretsUser, blobContributor, postgresDatabase, postgresAllowAzure]
  properties: {
    environmentId: appEnvironment.id
    workloadProfileName: 'Consumption'
    configuration: {
      ingress: { external: false, targetPort: 8000, transport: 'auto', allowInsecure: false }
      registries: registries
      secrets: vaultSecrets
    }
    template: {
      containers: [
        {
          name: 'api'
          image: '${image}/backend:${imageTag}'
          resources: { cpu: json('0.5'), memory: '1Gi' }
          env: backendEnv
          probes: [
            { type: 'Liveness', httpGet: { path: '/health/live', port: 8000 }, periodSeconds: 15 }
            { type: 'Readiness', httpGet: { path: '/health/ready', port: 8000 }, periodSeconds: 10 }
          ]
        }
      ]
      scale: {
        minReplicas: 1
        maxReplicas: 5
        rules: [{ name: 'http', http: { metadata: { concurrentRequests: '50' } } }]
      }
    }
  }
}

resource worker 'Microsoft.App/containerApps@2024-03-01' = {
  name: 'ca-iip-worker-${environmentName}'
  location: location
  tags: tags
  identity: appIdentity
  dependsOn: [acrPull, vaultSecretsUser, blobContributor, postgresDatabase, postgresAllowAzure]
  properties: {
    environmentId: appEnvironment.id
    workloadProfileName: 'Consumption'
    configuration: {
      registries: registries
      secrets: vaultSecrets
    }
    template: {
      containers: [
        {
          name: 'worker'
          image: '${image}/backend:${imageTag}'
          command: ['iip', 'worker']
          resources: { cpu: json('0.5'), memory: '1Gi' }
          env: backendEnv
        }
      ]
      // Jobs are claimed with SKIP LOCKED, so replicas can be added freely.
      scale: { minReplicas: 1, maxReplicas: 3 }
    }
  }
}

resource web 'Microsoft.App/containerApps@2024-03-01' = {
  name: 'ca-iip-web-${environmentName}'
  location: location
  tags: tags
  identity: appIdentity
  dependsOn: [acrPull]
  properties: {
    environmentId: appEnvironment.id
    workloadProfileName: 'Consumption'
    configuration: {
      ingress: { external: true, targetPort: 8080, transport: 'auto', allowInsecure: false }
      registries: registries
    }
    template: {
      containers: [
        {
          name: 'web'
          image: '${image}/web:${imageTag}'
          resources: { cpu: json('0.25'), memory: '0.5Gi' }
          env: [{ name: 'API_UPSTREAM', value: 'https://${api.properties.configuration.ingress.fqdn}' }]
          probes: [{ type: 'Liveness', httpGet: { path: '/healthz', port: 8080 }, periodSeconds: 15 }]
        }
      ]
      scale: { minReplicas: 1, maxReplicas: 3 }
    }
  }
}

resource migrate 'Microsoft.App/jobs@2024-03-01' = {
  name: 'caj-iip-migrate-${environmentName}'
  location: location
  tags: tags
  identity: appIdentity
  dependsOn: [acrPull, vaultSecretsUser, postgresDatabase, postgresAllowAzure]
  properties: {
    environmentId: appEnvironment.id
    workloadProfileName: 'Consumption'
    configuration: {
      triggerType: 'Manual'
      replicaTimeout: 600
      replicaRetryLimit: 1
      manualTriggerConfig: { parallelism: 1, replicaCompletionCount: 1 }
      registries: registries
      secrets: vaultSecrets
    }
    template: {
      containers: [
        {
          name: 'migrate'
          image: '${image}/backend:${imageTag}'
          command: ['iip', 'migrate']
          resources: { cpu: json('0.25'), memory: '0.5Gi' }
          env: backendEnv
        }
      ]
    }
  }
}

output webUrl string = web.properties.configuration.ingress.fqdn
output migrateJobName string = migrate.name
output identityClientId string = identity.properties.clientId
output keyVaultName string = vault.name
