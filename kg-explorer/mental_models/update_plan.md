# Documentation Update Plan

Generated: 2026-04-28T08:58:02Z
Outdated facts: 18 of 102 perishable facts need updates

## Summary

| File | Updates | Confidence |
|------|---------|------------|
| mission-critical-application-design.md | 1 | 1 high |
| mission-critical-application-platform.md | 1 | 1 high |
| mission-critical-data-platform.md | 6 | 1 medium, 5 high |
| mission-critical-health-modeling.md | 1 | 1 high |
| mission-critical-networking-connectivity.md | 5 | 3 medium, 2 high |
| mission-critical-security.md | 2 | 2 medium |
| whats-new.md | 2 | 1 medium, 1 high |

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

### mission-critical/mission-critical-application-platform.md

#### Under "#### Design considerations and recommendations for Azure Logic Apps" (line ~320)

**Entity:** North Star Architecture

**Current text:**
> We recommend the use of private endpoints for restricting access to private virtual networks. They can also mitigate data exfiltration risks, like malicious admin scenarios.
> 
> You need to use code scanning tools on Azure Functions code and integrate those tools with CI/CD pipelines.
> 
> #### Design considerations and recommendations for Azure Logic Apps
> 
> Like Azure Functions, Logic Apps uses built-in triggers for event-driven processing. However, instead of deploying application code, you can create logic apps by using a graphical user interface that supports blocks like conditionals, loops, and other constructs.
> 
> Multiple [deployment modes](/azure/logic-apps/single-tenant-overview-compare) are available. We recommend the Standard mode to ensure a single-tenant deployment and mitigate noisy neighbor scenarios. This mode uses the containerized single-tenant Logic Apps runtime, which is based on Azure Functions. In this mode, the logic app can have multiple stateful and stateless workflows. You should be aware of the configuration limits.
> 
> ## Constrained migrations via IaaS

**Outdated claim:**
> North Star architecture is the recommended cloud-native baseline pattern for mission-critical workloads

**Current information:**
> Microsoft's mission-critical architecture documentation recommends a 'north star design approach' as part of the architecture pattern, but does not use the exact phrase 'North Star architecture' as a named pattern nor call it the 'recommended cloud-native baseline pattern'. It is a design approach within the broader mission-critical guidance.

**Suggested replacement:**
> Run with `--suggest` to generate LLM suggestions

**Source:** https://learn.microsoft.com/en-us/azure/well-architected/mission-critical/mission-critical-architecture-pattern
**Confidence:** medium
**Location confidence:** 1.00
**Verified:** 2026-04-28T08:44:24+00:00

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

#### Under "### Design Recommendations" (line ~497)

**Entity:** Continuous Backups

**Current text:**
> - Evaluate application traffic patterns to select an optimal option for [provisioned throughput types](/azure/cosmos-db/how-to-choose-offer).
>   - Consider auto-scale provisioned throughput to automatically level-out workload demand.
> 
> - Evaluate Microsoft [performance tips for Azure Cosmos DB](/azure/cosmos-db/nosql/performance-tips) to optimize client-side and server-side configuration for improved latency and throughput.
> 
> - When using AKS as the compute platform: For query-intensive workloads, select an AKS node SKU that has accelerated networking enabled to reduce latency and CPU jitters.
> 
> - For single write region deployments, it's strongly recommended to configure Azure Cosmos DB for [automatic failover](/azure/cosmos-db/high-availability#multi-region-accounts-with-a-single-write-region-write-region-outage).
> 
> - Load-level through the use of asynchronous non-blocking messaging within system flows, which write updates to Azure Cosmos DB.
>   - Consider patterns such as [Command and Query Responsibility Segregation](/azure/architecture/patterns/cqrs) and [Event Sourcing](/azure/architecture/patterns/event-sourcing).

**Outdated claim:**
> Continuous backups provide recovery points across the last 30 days for Azure Cosmos DB

**Current information:**
> Azure Cosmos DB continuous backup offers two tiers: 7-day retention (default) and 30-day retention. The 30-day retention is available but not the only option.

**Suggested replacement:**
> Run with `--suggest` to generate LLM suggestions

**Source:** https://learn.microsoft.com/en-us/azure/cosmos-db/continuous-backup-restore-introduction
**Confidence:** medium
**Location confidence:** 0.93
**Verified:** 2026-04-28T08:45:16+00:00

---

#### Under "### Design considerations" (line ~565)

**Entity:** Single Server

**Current text:**
> - Azure SQL Database Hyperscale tier, when configured with at least two replicas, has an availability SLA of 99.99%.
> 
> - Compute costs associated with Azure SQL Database can be reduced using a [Reservation Discount](/azure/cost-management-billing/reservations/understand-reservation-charges).
>   - It's not possible to apply reserved capacity for DTU-based databases.
> 
> - [Point-in-time restore](/azure/azure-sql/database/recovery-using-backups#point-in-time-restore) can be used to return a database and contained data to an earlier point in time.
> 
> - [Geo-restore](/azure/sql-database/sql-database-recovery-using-backups) can be used to recover a database from a geo-redundant backup.
> 
> **Azure Database For PostgreSQL**

**Outdated claim:**
> Azure Database for PostgreSQL Single Server has a 99.99% SLA

**Current information:**
> Azure Database for PostgreSQL Single Server reached end of life and is deprecated. Its SLA was 99.99%, but the service is no longer available for new or existing workloads, having been replaced by Flexible Server.

**Suggested replacement:**
> Run with `--suggest` to generate LLM suggestions

**Source:** https://learn.microsoft.com/en-us/azure/postgresql/single-server/overview-single-server
**Confidence:** medium
**Location confidence:** 0.90
**Verified:** 2026-04-28T08:45:44+00:00

---

#### Under "### Design considerations" (line ~401)

**Entity:** Continuous Backup

**Current text:**
>       - It's not possible to select a subset of containers to restore.
>   - [Continuous](/azure/cosmos-db/continuous-backup-restore-introduction) backup mode allows for a restore to any point of time within the last 30 days.
>     - Restore operations can be performed to return to a specific point in time (PITR) with a one-second granularity.
>     - The available window for restore operations is up to 30 days.
>       - It's also possible to restore to the resource instantiation state.
>     - Continuous backups are taken within every Azure region where the Azure Cosmos DB account exists.
>       - Continuous backups are stored within the same Azure region as each Azure Cosmos DB replica, using Locally-Redundant Storage (LRS) or Zone Redundant Storage (ZRS) within regions that support Availability Zones.
>     - A self-service restore can be performed using the [Azure portal](/azure/cosmos-db/restore-account-continuous-backup#restore-account-portal) or IaC artifacts such as [ARM templates](/azure/cosmos-db/restore-account-continuous-backup#restore-arm-template).
>     - There are several [limitations](/azure/cosmos-db/continuous-backup-restore-introduction#current-limitations) with Continuous Backup.
>       - The continuous backup mode isn't currently available in a multi-region-write configuration.
>       - Only Azure Cosmos DB for NoSQL and Azure Cosmos DB for MongoDB can be configured for Continuous backup at this time.

**Outdated claim:**
> Continuous backup enables point-in-time restore via Azure portal or ARM templates

**Current information:**
> Continuous backup restore can be triggered via Azure portal, Azure CLI, Azure PowerShell, or ARM templates. The claim is partially correct but incomplete.

⚠️ **Manual review needed** — location confidence: 0.64

**Source:** https://learn.microsoft.com/en-us/azure/cosmos-db/continuous-backup-restore-introduction
**Confidence:** medium
**Location confidence:** 0.64
**Verified:** 2026-04-28T08:47:16+00:00

---

### mission-critical/mission-critical-health-modeling.md

#### Under "### Design considerations" (line ~345)

**Entity:** Action Groups

**Current text:**
> - Alerts can be defined within Log Analytics or Azure Monitor on the specific resource.
> 
> - Some metrics are only interrogatable within Azure Monitor, since not all diagnostic data points are made available within Log Analytics.
> 
> - The Azure Monitor Alerts API can be used to retrieve active and historic alerts.
> 
> - There are subscription limits related to alerting and action groups, which must be designed for:
>   - [Limits](/azure/azure-resource-manager/management/azure-subscription-service-limits#alerts) exist for the number of configurable alert rules.
>   - The Alerts API has [throttling limits](/azure/azure-resource-manager/management/azure-subscription-service-limits#alerts-api), which should be considered for extreme usage scenarios.
>   - Action Groups have [several hard limits](/azure/azure-resource-manager/management/azure-subscription-service-limits#action-groups) for the number of configurable responses, which must be designed for.
>     - Each response type has a limit of 10 actions, apart from email, which has a limit of 1,000 actions.

**Outdated claim:**
> Action Groups have hard limits on configurable responses

**Current information:**
> Action Groups have specific numeric limits (e.g., 10 webhook actions per group, 1500 webhook calls/min/subscription, 10 email actions per group, etc.) but the 'Maximum limit' column shows 'Same as Default' — meaning these are fixed limits, not configurable.

**Suggested replacement:**
> Run with `--suggest` to generate LLM suggestions

**Source:** https://github.com/MicrosoftDocs/azure-monitor-docs/blob/main/articles/azure-monitor/alerts/includes/azure-monitor-limits-action-groups.md
**Confidence:** medium
**Location confidence:** 1.00
**Verified:** 2026-04-28T08:47:44+00:00

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

#### Under "### Design considerations" (line ~103)

**Entity:** Azure Standard Load Balancer

**Current text:**
> 
> - The DNS response is cached and reused by the client for a specified Time-To-Live (TTL) period, and requests made during this period will go directly to the backend endpoint without Traffic Manager interaction. Eliminates the extra connectivity step that provides cost benefits compared to Front Door.
> 
> - Since the request is made directly from the client to the backend service, any protocol supported by the backend can be leveraged.
> 
> - Similar to Azure Front Door, Azure Traffic Manager also relies on health probes to understand if a backend is healthy and operating normally. If another value is returned or nothing is returned, the routing service recognizes ongoing issues and will stop routing requests to that specific backend.
>   - However, unlike with Azure Front Door this removal of unhealthy backends isn't instantaneous since clients will continue to create connections to the unhealthy backend until the DNS TTL expires and a new backend endpoint is requested from the Traffic Manager service.
>   - In addition, even when the TTL expires, there no guarantee that public DNS servers will honor this value, so DNS propagation can actually take much longer to occur. This means that traffic may continue to be sent to the unhealthy endpoint for a sustained period of time.  
> 
> **Azure Standard Load Balancer**

**Outdated claim:**
> Azure Standard Load Balancer cross-region capability is available in preview and not recommended for mission-critical workloads

**Current information:**
> Azure cross-region Load Balancer reached General Availability (GA) status. It is no longer merely in preview.

**Suggested replacement:**
> Run with `--suggest` to generate LLM suggestions

**Source:** https://learn.microsoft.com/en-us/azure/load-balancer/cross-region-overview
**Confidence:** medium
**Location confidence:** 0.88
**Verified:** 2026-04-28T08:41:25+00:00

---

#### Under "#### Connected virtual networks" (line ~316)

**Entity:** Virtual Private Network

**Current text:**
> - The application network design must align with the broader network architecture, particularly concerning topics such as addressing and routing.
> 
> - Overlapping IP address spaces across Azure regions or on-premises networks will create major contention when network integration is considered.
>   - A virtual network resource can be updated to consider additional address space, however, when a virtual network address space of a peered network changes a [sync on the peering link is required](https://azure.microsoft.com/blog/how-to-resize-azure-virtual-networks-that-are-peered-now-in-preview/), which will temporarily disable peering.
>   - Azure reserves five IP addresses within each subnet, which should be considered when determining appropriate sizes for application virtual networks and encompassed subnets.
>   - Some Azure services require dedicated subnets, such as Azure Bastion, Azure Firewall, or Azure Virtual Network Gateway. The size of these service subnets is very important, since they should be large enough to support all current instances of the service considering future scale requirements, but not so large as to unnecessarily waste addresses.
> 
> - When on-premises or cross-cloud network integration is required, Azure offers two different solutions to establish a secure connection.
>   - An ExpressRoute circuit can be sized to provide bandwidths up to 100 Gbps.
>   - A Virtual Private Network (VPN) can be sized to provide aggregated bandwidth up to 10 Gbps in hub and spoke networks, and up to 20 Gbps in Azure Virtual WAN.

**Outdated claim:**
> VPN provides aggregated bandwidth up to 10 Gbps in hub-and-spoke networks

**Current information:**
> The highest VPN Gateway SKU (VpnGw5) provides up to 10 Gbps aggregate throughput across all tunnels, but per-tunnel throughput maxes out at ~2.3 Gbps. The 10 Gbps figure refers to the aggregate gateway benchmark throughput for the VpnGw5 SKU, which is specific to Virtual WAN/hub scenarios. The claim about 'hub-and-spoke networks' likely conflates VPN Gateway with Azure Virtual WAN's hub VPN capability.

**Suggested replacement:**
> Run with `--suggest` to generate LLM suggestions

**Source:** https://github.com/MicrosoftDocs/azure-docs/blob/main/includes/vpn-gateway-table-sku-performance.md
**Confidence:** medium
**Location confidence:** 0.93
**Verified:** 2026-04-28T08:48:35+00:00

---

### mission-critical/mission-critical-security.md

#### Under "### Design recommendations" (line ~86)

**Entity:** Azure Defender

**Current text:**
>     - Additional security gates may come at a trade-off in terms of agility and should be carefully evaluated, with consideration given to how agility can be maintained even with manual gates.
> 
> - Define an appropriate security posture for all lower environments to ensure key vulnerabilities are mitigated.
>   - Do not apply the same security posture as production, particularly with regard to data exfiltration, unless regulatory requirements stipulate the need to do so, since this will significantly compromise developer agility.
> 
> - Enable Microsoft Defender for Cloud (formerly known as Azure Security Center) for all subscriptions that contain the resources for a mission-critical workload.
>   - Use Azure Policy to enforce compliance.
>   - Enable Azure Defender for all services that support the capability.
> 
> - Embrace [DevSecOps](/azure/devops/devsecops/) and implement security testing within CI/CD pipelines.
>   - Test results should be measured against a compliant security posture to inform release approvals, be they automated or manual.

**Outdated claim:**
> Azure Defender is enabled for all supporting services

**Current information:**
> Azure Defender has been rebranded to Microsoft Defender for Cloud. The equivalent current recommendation would be to enable Microsoft Defender for Cloud plans for all supporting services.

⚠️ **Manual review needed** — location confidence: 0.75

**Source:** https://learn.microsoft.com/en-us/azure/defender-for-cloud/defender-for-cloud-introduction
**Confidence:** medium
**Location confidence:** 0.75
**Verified:** 2026-04-28T08:56:47+00:00

---

#### Under "# Security considerations for mission-critical workloads on Azure" (line ~14)

**Entity:** Mission-Critical Open Source Project

**Current text:**
> 
> # Security considerations for mission-critical workloads on Azure
> 
> Security is one of the foundational design principles and also a key design area that must be treated as a first-class concern within the mission-critical architectural process.
> 
> Given that the primary focus of a mission-critical design is to maximize reliability so that the application remains performant and available, the security considerations and recommendations applied within this design area will focus on mitigating threats with the capacity to impact availability and hinder overall reliability. For example, successful Denial-Of-Service (DDoS) attacks are known to have a catastrophic impact on availability and performance. How an application mitigates those attack vectors, such as SlowLoris will impact the overall reliability. So, the application must be fully protected against threats intended to directly or indirectly compromise application reliability to be truly mission critical in nature.
> 
> It's also important to note that there are often significant trade-offs associated with a hardened security posture, particularly with respect to performance, operational agility, and in some cases reliability. For example, the inclusion of inline Network Virtual Appliances (NVA) for Next-Generation Firewall (NGFW) capabilities, such as deep packet inspection, will introduce a significant performance penalty, additional operational complexity, and a reliability risk if scalability and recovery operations are not closely aligned with that of the application. It's therefore essential that additional security components and practices intended to mitigate key threat vectors are also designed to support the reliability target of an  application, which will form a key aspect of the recommendations and considerations presented within this section.
> 
> > [!IMPORTANT]
> > This article is part of the [Azure Well-Architected mission-critical workload](index.yml) series. If you aren't familiar with this series, we recommend you start with [what is a mission-critical workload?](mission-critical-overview.md#what-is-a-mission-critical-workload)

**Outdated claim:**
> The Mission-Critical open source project is hosted on GitHub under the Azure/AlwaysOn repository

**Current information:**
> The project was originally at Azure/AlwaysOn but has been renamed to Azure/Mission-Critical. Furthermore, the repository is no longer actively maintained.

⚠️ **Manual review needed** — location confidence: 0.62

**Source:** https://github.com/Azure/Mission-Critical
**Confidence:** high
**Location confidence:** 0.62
**Verified:** 2026-04-28T08:57:10+00:00

---

### whats-new.md

#### Under "### Azure feature updates" (line ~187)

**Entity:** Azure Application Gateway V2

**Current text:**
> - [Architecture strategies for designing a reliable monitoring and alerting strategy](./reliability/monitoring.md): We refreshed the monitoring and alerting strategy guidance, added new recommendations for monitoring network traffic to improve reliability, and expanded best practices for using Azure tools in incident response.
> 
> - [Architecture best practices for Azure Files](./service-guides/azure-files.md): We revised the Azure Files guide to clarify terminology, update redundancy and billing model details, add guidance for SSD file shares and metadata caching, and include total cost of ownership (TCO) resources. We also added guidance about using the Azure File Sync Arc extension for hybrid environments.
> 
> ### Azure feature updates
> 
> This month, we incorporated newly released Azure features from the [Azure updates feed](https://azure.microsoft.com/updates/) into our guidance. The most significant examples are highlighted below.
> 
> - [Architecture best practices for Azure App Service (Web Apps)](./service-guides/app-service-web-apps.md): Added IPv6 support considerations for scaling and clarified related network protocol guidance.
> 
> - [Architecture best practices for Azure Firewall](./service-guides/azure-firewall.md): Incorporated guidance for Resource Health monitoring, explicit proxy configuration, customer-controlled maintenance, and change tracking capabilities.

**Outdated claim:**
> Azure Application Gateway v2 has AI-powered threat analysis and response capabilities

**Current information:**
> Azure Application Gateway v2 includes WAF capabilities but is not documented as having AI-powered threat analysis and response. AI-powered threat analysis is more associated with Azure DDoS Protection or Microsoft Defender for Cloud.

**Suggested replacement:**
> Run with `--suggest` to generate LLM suggestions

**Source:** https://learn.microsoft.com/en-us/azure/application-gateway/overview-v2
**Confidence:** medium
**Location confidence:** 0.84
**Verified:** 2026-04-28T08:50:49+00:00

---

#### Under "### Updated articles" (line ~67)

**Entity:** Azure NetApp Files

**Current text:**
> - [Align technical strategy with business requirements](./architect-role/design-business-requirements.md): Learn about a five-step process to turn business needs into actionable technical requirements. This guidance helps architects clarify goals, uncover real motivations, evaluate trade-offs, and recommend strategies that balance technical soundness with business priorities.
> 
> - [Architecture best practices for Azure Virtual WAN](./service-guides/virtual-wan-service-guide.md): Get architectural best practices for Virtual WAN that align with the Well-Architected Framework pillars. Learn how to design for reliability, security, cost optimization, operational excellence, and performance efficiency, with practical recommendations for connectivity, redundancy, monitoring, and scaling in global networks.
> 
> ### Updated articles
> 
> - [Architecture best practices for Azure Event Hubs](./service-guides/azure-event-hubs.md): We improved clarity and modernized language across Operational Excellence and Performance Efficiency sections. We added new automation and policy-based cost control recommendations, streamlined configuration advice, and enhanced guidance for monitoring, scaling, and testing. These changes make it easier to apply best practices and optimize your Event Hubs workloads.
> 
> - [Develop an architecture design specification](./architect-role/architecture-design-specification.md): We clarified the importance of aligning design decisions with business needs and stakeholder goals. We added references to the business requirements guide, condensed the functional specification section, and added a link to detailed disaster recovery planning resources. These changes make it easier to create clear, actionable architecture specifications that support both technical and business objectives.
> 
> - [Solution architect's responsibilities and guiding principles](./architect-role/fundamentals.md): We clarified responsibilities, provided a practical checklist of deliverables, and emphasized the importance of aligning architecture with business requirements. We streamlined the guiding principles, added actionable advice for decision-making, supportability, and continuous learning, and improved guidance about how to collaborate with platform teams. These changes help architects deliver clear, effective, and adaptable solutions.

**Outdated claim:**
> Azure NetApp Files offers a Flexible service level

**Current information:**
> Azure NetApp Files offers three service levels: Standard, Premium, and Ultra. There is no 'Flexible' service level.

⚠️ **Manual review needed** — location confidence: 0.75

**Source:** https://learn.microsoft.com/en-us/azure/azure-netapp-files/azure-netapp-files-service-levels
**Confidence:** medium
**Location confidence:** 0.75
**Verified:** 2026-04-28T08:57:14+00:00

---
