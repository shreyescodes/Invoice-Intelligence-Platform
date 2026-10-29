// Container registry, deployed first so CI can push images before the apps reference them.
targetScope = 'resourceGroup'

@description('Short environment name used in resource names: lowercase letters and digits, e.g. prod.')
@minLength(2)
@maxLength(8)
param environmentName string

param location string = resourceGroup().location

var suffix = uniqueString(resourceGroup().id, environmentName)

resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: 'acriip${environmentName}${suffix}'
  location: location
  sku: { name: 'Basic' }
  properties: {
    adminUserEnabled: false
    publicNetworkAccess: 'Enabled'
  }
}

output name string = registry.name
output loginServer string = registry.properties.loginServer
