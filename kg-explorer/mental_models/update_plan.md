# Documentation Update Plan

Generated: 2026-04-28T08:23:59Z
Outdated facts: 7 of 35 perishable facts need updates

## Summary

| File | Updates | Confidence |
|------|---------|------------|
| mission-critical-application-design.md | 1 | 1 high |
| mission-critical-data-platform.md | 3 | 3 high |
| mission-critical-networking-connectivity.md | 3 | 3 medium |

---

## Updates

### mission-critical/mission-critical-application-design.md

#### Under "### Example scale units" (line ~31)

**Entity:** AKS

**Current text:**
> ### Example scale units
> 
> The following image shows the possible scopes for scale units. The scopes range from microservice pods to cluster nodes and regional deployment stamps.
> 
> :::image type="content" source="./images/mission-critical-scale-units.png" alt-text="Diagram that shows multiple scopes for scale units." lightbox="./images/mission-critical-scale-units.png ":::
> 
> ### Design considerations
> 
> - **Scope**. The scope of a scale unit, the relationship between scale units, and their components should be defined according to a capacity model. Take into consideration non-functional requirements for performance.
> 
> - **Scale limits**. [Azure subscription scale limits and quotas](/azure/azure-resource-manager/management/azure-subscription-service-limits) might have a bearing on application design, technology choices, and the definition of scale units. Scale units can help you bypass the scale limits of a service. For example, if an AKS cluster in one unit can have only 1,000 nodes, you can use two units to increase that limit to 2,000 nodes.

**Outdated claim:**
> AKS has a scale limit of 1,000 nodes per cluster

**Current information:**
> AKS supports up to 5,000 nodes per cluster.

**Suggested replacement:**
> Run with `--suggest` to generate LLM suggestions

**Source:** https://learn.microsoft.com/en-us/azure/aks/quotas-skus-regions
**Confidence:** high
**Location confidence:** 0.92
**Verified:** 2026-04-28T06:43:16+00:00

---

### mission-critical/mission-critical-data-platform.md

#### Under "### Design considerations" (line ~409)

**Entity:** Azure Synapse Link

**Current text:**
>     - There are several [limitations](/azure/cosmos-db/continuous-backup-restore-introduction#current-limitations) with Continuous Backup.
>       - The continuous backup mode isn't currently available in a multi-region-write configuration.
>       - Only Azure Cosmos DB for NoSQL and Azure Cosmos DB for MongoDB can be configured for Continuous backup at this time.
>       - If a container has TTL configured, restored data that has exceeded its TTL may be *immediately deleted*
>     - A restore operation creates a new Azure Cosmos DB account for the point-in-time restore.
>     - There's an [additional storage cost](/azure/cosmos-db/continuous-backup-restore-introduction#continuous-backup-pricing) for Continuous backups and restore operations.
> 
> - Existing Azure Cosmos DB accounts can be migrated from Periodic to Continuous, but not from Continuous to Periodic; migration is one-way and not reversible.
> 
> - Each Azure Cosmos DB backup is composed of the data itself and configuration details for provisioned throughput, indexing policies, deployment region(s), and container TTL settings.
>   - Backups don't contain [firewall settings](/azure/templates/microsoft.documentdb/databaseaccounts?tabs=json#ipaddressorrange-object), [virtual network access control lists](/azure/templates/microsoft.documentdb/databaseaccounts/privateendpointconnections), [private endpoint settings](/azure/templates/microsoft.documentdb/databaseaccounts/privateendpointconnections), [consistency settings](/azure/templates/microsoft.documentdb/databaseaccounts?tabs=json#consistencypolicy-object) (an account is restored with session consistency), [stored procedures](/azure/templates/microsoft.documentdb/databaseaccounts/sqldatabases/containers/storedprocedures), [triggers](/azure/templates/microsoft.documentdb/databaseaccounts/sqldatabases/containers/triggers), [UDFs](/azure/templates/microsoft.documentdb/databaseaccounts/sqldatabases/containers/userdefinedfunctions), or [multi-region settings](/azure/templates/microsoft.documentdb/databaseaccounts?tabs=json#Location).

**Outdated claim:**
> Analytical store data is not included in Azure Cosmos DB backups

**Current information:**
> Azure Cosmos DB continuous backup now includes analytical store data. Earlier documentation stated analytical store was excluded from backups, but this has been updated.

**Suggested replacement:**
> Run with `--suggest` to generate LLM suggestions

**Source:** https://learn.microsoft.com/en-us/azure/cosmos-db/synapse-link-frequently-asked-questions#backup
**Confidence:** medium
**Location confidence:** 1.00
**Verified:** 2026-04-28T06:59:57+00:00

---

#### Under "### Design Considerations" (line ~656)

**Entity:** Azure Cache For Redis

**Current text:**
> Azure provides several services with applicable capabilities for caching key data structures, with Azure Cache for Redis positioned to abstract and optimize data platform read access. This section will therefore focus on the optimal usage of Azure Cache for Redis in scenarios where additional read performance and data access durability is required.
> 
> ### Design Considerations
> 
> - A caching layer provides additional data access durability since even if an outage impacting the underlying data technologies, an application data snapshot can still be accessed through the caching layer.
> 
> - In certain workload scenarios, in-memory caching can be implemented within the application platform itself.
> 
> **Azure Cache for Redis**
> 
> - Redis cache is an open source NoSQL key-value in-memory storage system.

**Outdated claim:**
> Azure Cache for Redis offers Premium, Enterprise, and Enterprise Flash tiers

**Current information:**
> Azure Cache for Redis offers Basic, Standard, Premium, Enterprise, and Enterprise Flash tiers

**Suggested replacement:**
> Run with `--suggest` to generate LLM suggestions

**Source:** https://learn.microsoft.com/en-us/azure/azure-cache-for-redis/cache-overview#service-tiers
**Confidence:** medium
**Location confidence:** 0.80
**Verified:** 2026-04-28T07:03:07+00:00

---

#### Under "### Design considerations" (line ~571)

**Entity:** Azure Database For PostgreSQL

**Current text:**
> 
> - [Geo-restore](/azure/sql-database/sql-database-recovery-using-backups) can be used to recover a database from a geo-redundant backup.
> 
> **Azure Database For PostgreSQL**
> 
> - Azure Database For PostgreSQL is offered in three different deployment options:
>   - Single Server, SLA 99.99%
>   - Flexible Server, which offers Availability Zone redundancy, SLA 99.99%
>   - Hyperscale (Citus), SLA 99.95% when High Availability mode is enabled.
> 
> - [Hyperscale (Citus)](/azure/postgresql/tutorial-hyperscale-shard) provides dynamic scalability through sharding without application changes.

**Outdated claim:**
> Azure Database for PostgreSQL is offered in Single Server, Flexible Server, and Hyperscale (Citus) deployment options

**Current information:**
> Single Server is retired (end of life March 28, 2025) and Hyperscale (Citus) has been merged into Flexible Server. The current deployment option is Flexible Server only.

**Suggested replacement:**
> Run with `--suggest` to generate LLM suggestions

**Source:** https://learn.microsoft.com/en-us/azure/postgresql/single-server/whats-happening-to-postgresql-single-server
**Confidence:** high
**Location confidence:** 1.00
**Verified:** 2026-04-28T07:03:25+00:00

---

### mission-critical/mission-critical-networking-connectivity.md

#### Under "### Design considerations" (line ~177)

**Entity:** Azure CDN

**Current text:**
> The network ingress path for a mission-critical application must also consider application delivery services to ensure secure, reliable, and scalable ingress traffic.
> 
> This section builds on [global routing recommendations](#design-recommendations) by exploring key application delivery capabilities, considering relevant services such as Azure Standard Load Balancer, Azure Application Gateway, and Azure API Management.
> 
> ### Design considerations
> 
> - TLS encryption is critical to ensure the integrity of inbound user traffic to a mission-critical application, with **TLS Offloading** applied only at the point of a stamp's ingress to decrypt incoming traffic. TLS Offloading Requires the private key of the TLS certificate to decrypt traffic.
> 
> - A **Web Application Firewall** provides protection against common web exploits and vulnerabilities, such as SQL injection or cross site scripting, and is essential to achieve the maximum reliability aspirations of a mission-critical application.
> 
> - Azure WAF provides out-of-the-box protection against the top 10 OWASP vulnerabilities using managed rule sets.

**Outdated claim:**
> Azure CDN supports Azure WAF enablement in public preview

**Current information:**
> The Microsoft Azure updates page still references WAF for Azure CDN from Microsoft as being 'in preview'. However, note that Azure CDN from Microsoft (classic) is being retired in favor of Azure Front Door, which has GA WAF support. The claim about public preview was accurate at the time but the feature/product is being deprecated.

⚠️ **Manual review needed** — location confidence: 0.75

**Source:** https://azure.microsoft.com/en-us/updates?id=azure-web-application-firewall-waf-for-azure-content-delivery-network-cdn-from-microsoft-service-is-in-preview
**Confidence:** medium
**Location confidence:** 0.75
**Verified:** 2026-04-28T07:00:48+00:00

---

#### Under "### Design Considerations" (line ~478)

**Entity:** Calico

**Current text:**
>   > [!NOTE]
>   > Azure CNI requires more IP address space compared to Kubenet. Proper upfront planning and sizing of the network is required. For more information, refer to the [Azure CNI documentation](/azure/aks/concepts-network#azure-cni-advanced-networking).
> 
> - By default, pods are non-isolated and accept traffic from any source and can send traffic to any destination; a pod can communicate with every other pod in a given Kubernetes cluster; Kubernetes doesn't ensure any network level isolation, and doesn't isolate namespaces at the cluster level.
> 
> - Communication between Pods and Namespaces can be isolated using [Network Policies](https://kubernetes.io/docs/concepts/services-networking/network-policies/). Network Policy is a Kubernetes specification that defines access policies for communication between Pods. Using Network Policies, an ordered set of rules can be defined to control how traffic is sent/received, and applied to a collection of pods that match one or more label selectors.
> 
>   - AKS supports two plugins that implement Network Policy, *Azure* and *Calico*. Both plugins use Linux IPTables to enforce the specified policies. See [Differences between Azure and Calico policies and their capabilities](/azure/aks/use-network-policies#differences-between-azure-and-calico-policies-and-their-capabilities) for more details.
>   - Network policies don't conflict since they're additive.
>   - For a network flow between two pods to be allowed, both the egress policy on the source pod and the ingress policy on the destination pod need to allow the traffic.
>   - The network policy feature can only be enabled at cluster instantiation time. It's not possible to enable network policy on an existing AKS cluster.

**Outdated claim:**
> Calico has a richer feature set than Azure network policies including Windows node support

**Current information:**
> Azure Network Policy Manager supports both Linux and Windows Server 2022, while Calico supports Linux and Windows Server 2019/2022. Both support Windows nodes. Azure NPM is described as simpler while Calico has advanced features like egress and DNS policies, but Windows support is not unique to Calico.

⚠️ **Manual review needed** — location confidence: 0.71

**Source:** https://microsoft.github.io/k8s-on-azure-workshop/module-4/3_security/3_network_policy/index.html
**Confidence:** medium
**Location confidence:** 0.71
**Verified:** 2026-04-28T07:05:23+00:00

---

#### Under "## Inter-zone and inter-region Connectivity" (line ~416)

**Entity:** Availability Zone

**Current text:**
> - Ensure incremental firewall policies are delegated to application security teams via role-based access control to allow for application policy autonomy.
> 
> ## Inter-zone and inter-region Connectivity
> 
> While the application design strongly advocates independent regional deployment stamps, many application scenarios may still require network integration between application components deployed within different zones or Azure regions, even if only under degraded service circumstances. The method by which inter-zone and inter-region communication is achieved has a significant bearing on overall performance and reliability, which will be explored through the considerations and recommendations within this section.
> 
> ### Design Considerations
> 
> - The application design approach for a mission-critical application endorses the use of independent regional deployments with zone redundancy applied at all component levels within a single region.
> 
> - An [Availability Zone (AZ)](/azure/reliability/availability-zones-overview) is a physically separate data center location within an Azure region, providing physical and logical fault isolation up to the level of a single data center.

**Outdated claim:**
> Availability Zones provide guaranteed sub-2ms inter-zone latency

**Current information:**
> Azure documents a round-trip latency of less than 2ms as a design goal between Availability Zones, but it is not a guaranteed SLA commitment. The actual wording is that AZs deliver low-latency networking with round-trip latency of less than 2ms, not a guarantee.

⚠️ **Manual review needed** — location confidence: 0.74

**Source:** https://learn.microsoft.com/en-us/azure/reliability/availability-zones-overview
**Confidence:** medium
**Location confidence:** 0.74
**Verified:** 2026-04-28T07:41:47+00:00

---
