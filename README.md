# nemutator the tentacle friend of kubernetes

This projects doesn't aim (yet) for a production ready solution, but mostly for a fast prototype of the concept itself.
One of the main reasons, is that the author (myself) believes that should be done within GoLang but speed-to-market is what is being targeted at first.

Nemutator want's to be the best friend of scheduler, but not to replace him. It's also gonna be a good friend of your secrets, as he will be able to "manage" 
them quite faster compared to agents, and overall with a much lower cost in terms of compute, complexity and design.
Some of the other features that I'll be trying to implement is an inline golang flamegrapher thru ebpf (that one that is open source around) and see how between
these results and the metrics, developers can understand better what their stuff do and how tu tune some values.
During these fun period of breaking things around, we'll see how Nemutator tries to find who are the worst guys of the cluster and how to keep them aside of your
precious workload in an automatic way without much effort.

In a nut shell, instead of trying to tell the scheduler or k8s what to really do and involve redeployments, constant changes, etc.. I'll try to "mutate" the
lifecycle of a pod and whenever is possible, prefer "re-create" over "restart" (or something that works in between).
Some good friend will be a restful interface that WILL help Nemutator to evict pods in order to adjust and shift the load accordingly.

If i make it works, we'll find some good golang comanches that can put good lines behind it and i'll move on into something new :P

Some of the features:
* Mutate limits & requests of pods by the mutation controller (simple example added)
* Get some meaningful metric from Prometheus and use it to make some sense on the resources (it is encouraged record rules to be created at prom side)
* Manipulate labels/annotations without redeploy deployments
* Inject secrets as env, where we will tie hashes/dictionaries within the deployments that ultimately translate in paths of vault, at a lower cost.
* Understand what is peak-season and what is off-season by himself, and apply different "brainset" on those two scenarios
* Profile some stuff, thru flamegraph/ebpf golangs, without break things
* Support some third party provider like datadog and datasources like Redis for caching or who knows..
* Improve overprovisioning shims with the help of Nemutator and ultimately see if we can reduce requests on off-peak and shrink even more in
  a more natural way without disruption
