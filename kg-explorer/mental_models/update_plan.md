# Documentation Update Plan

Generated: 2026-04-27T21:42:48Z
Outdated facts: 1 of 1 perishable facts need updates

## Summary

| File | Updates | Confidence |
|------|---------|------------|
| mission-critical-application-design.md | 1 | 1 high |

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
> AKS supports up to 5,000 nodes per cluster. The 1,000 node limit is the default, but higher limits are available.

**Suggested replacement:**
> Run with `--suggest` to generate LLM suggestions

**Source:** https://learn.microsoft.com/en-us/azure/aks/quotas-skus-regions
**Confidence:** medium
**Location confidence:** 0.92
**Verified:** 2026-04-27T21:42:34+00:00

---
