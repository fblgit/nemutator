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
![alt text](https://github.com/fblgit/nemutator/raw/main/images/Nemutator.png)

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

# Progress so far..
* Able to mutate resources:
  - Query Prometheus Metric for a pod (code is in simulation mode, gathering from other pod data for testing purposes)
  - Capable of min/avg/max both for CPU and MEM
  - Able to produce a simple logic of ratio% over existing requests/limits:
   . requests are produced from a % of the limits and not to be 1:1 as by default
* Able to mutate labels:
  - Query Redis to muate a Label Key 'nemu_label_<hash>' to 'whatever_is_the_label'
  - Query Redis to muate a Label Value 'nemu_label_value_<hash>' to 'whatever_is_the_label_content'
* Able to mutate annotations:
  - Query Redis to mutate an Annotation Key 'nemu_anno_<hash>' to 'whatever_is_the_annotation'
  - Query Redis to mutate an Annotation Value 'nemu_anno_value_<hash>' to 'whatever_is_the_annotation_content'
* Able to mutate env:
  - Query Redis to mutate a Env Value 'nemu_<hash>' to 'whatever_is_the_env_value' (have to fix this label to 'nemu_env_<hash>'
* Able to mutate image versions in a forceful manner
  - Query Redis to mutate Image Version 'ubuntu:14.04' vs 'nemu_image_ubuntu' to 'ubuntu:20.04'
* Created understanding for skipping all nemutator with an annotation:
  - nemutator.io/skip: true
* Crated understanding for skipping elements of the mutation with an annotation:
  - nemutator.io/skip-mutation: $verbs
  Where verbs so far are: env, labels, annotations, image, resources, containers, patch
* Created the first version of the metrics scraper:
  - Able to create a structure with pods, replicaset, deployments
  - Able to scrape metrics from pods and deployments (cpu & mem)
  - Able to scrape metrics for nodes (cpu & mem)
  - Able to individually update elements and reconciliate their relations without discarding useful data

# Usage of skip verbs:
Very simple, if you set skip annotation to true.. it won't do or even process anything. (Fast out)

If you set a verb of the list, it will skip it from processing that element/s. This have to be used with verbs separated by space. ex: env labels

Something useful that can be done is to just skip patch, that would process all the logic of all the realms and scenarios but won't produce any change.
It can be used, and should, as a way to dry-run what nemutator "would" do.

# Metrics Scraper
It looks something like this:
- Pods:
  'redis-master-0': {'containers': ['redis', 'metrics'],
                             'metrics': {'cpu': {'avg': 11.98,
                                                 'max': 17.96,
                                                 'min': 0.54},
                                         'mem': {'avg': 60.56,
                                                 'max': 60.56,
                                                 'min': 6.32}},
                             'namespace': 'redis'},
- Deployments:
                 'grafana': {'metrics': {'cpu': {'avg': 9.39,
                                                 'max': 17.23,
                                                 'min': 1.55},
                                         'mem': {'avg': 83.05,
                                                 'max': 83.05,
                                                 'min': 83.05}},
                             'namespace': 'monitoring',
                             'pods': ['grafana-77945f8f6f-n5szq'],
                             'replicas': 'grafana-77945f8f6f'},
- Nodes:
 ( need to finish this model )

# Thoughts
One of the scopes is to "somehow" help the scheduler. There are many different ways to mess the scheduler big time and there are many ways to produce affinity and antiaffinity.
With the two most common ways 'preferred' (soft) vs 'required' (hard) the way of implementing weights is crucial and how this ultimately ends into a pod can turn very bad..
As per this topic, I believe there is an imperative need of testing how this affects the behaviour of the scheduler in the field.

Some different approach such as Scheduler Score Plugins seems to be a more reasonable approach to influence the scheduler vs weights & affinity. It seems a more 'safe' and 'simpler' appraoch
to allow scheduler to determine where he thinks he can schedule the pod (if he can, after sort>filter stages) and then influence the score of the possible node.
In this way, we should be able to implement any sort of metric or algorythm/logic to compute a more optimal score over those resources. By example:
* Scheduler determines that pod A "can" go into Node1, Node6, Node8
* Scores can be calculated with a pattern like this:
- CPU Real Usage (Less is Better)
- Memory Pressure (Less is Better)
- Familiars of the Deployment within the node (Negative)
- Pods that consumes the deployment service and that are producing high net i/o between nodes (net i/o neighbour affinity)
- Nodes that are empty (overprovisioned buffer) that will suit this load better
- Nodes that despite a high consumption of memory, the compute seems at a low grade and our pod should be able to fit well

I have the impression that Scheduler will always prefer to push the container into the empty node, applying preference over "even" distribution. This is something that will produce inefficient sizing of the cluster when autoscalers with buffers are in place since there will be always empty nodes ready for the spike. The understanding of "even" and "efficient" are distant within the Scheduler understanding of the workload, and despite being simple and safe.. it is not the most optimal. Probably, within the right HPA values and a mechanism to alter Taints of the scaler node.. Scheduler should be able to efficiently make "efforts" to adjust the workload in a more efficient manner.

# Todo
* El Griego: The GoLang Agent Profiler:
  - I think it will be wise to apply profiling to pods that has been alive for longer periods. This will eventually flag leaks and other problems in the code.
  - There must be a mechanism to identify GoLang workload, as this tool would only support those. But how ? (if u give a label, then thats it.. but if not?)
* The Good & Ugly, the bad neighbours:
  - There must be a way to score pods from multiple metrics of prometheus. Injecting those labels to both the deployments and the pods is crucial. These label must be updated frequently as result of their historical score and their short term score. This will allow to group for a short space of time many kind of pods during off-peak and then spread them out during peak. The target is to allow shrinks in better ways. Having this label will improve substantially the performance and speed of the Score plugin, but it have to be maintained and refreshed async for a 'short' (now) score, 'usually' (avg) score, 'worst' (max) score..
  - Computing score for both a single pod and a whole deployment is pretty much needed. In together with the Score plugin for the scheduler, this simple bold metric should drive a big influencer on the Score.
  - example thoughts: it doesnt matter if my Deployment A is a big consumption element if right now there is no such compute demand. The capacity of shrinking and grouping old-bad vs now-good in a off-peak is crucial for resources efficiency
* Better Passwords Refresh:
  - This is a topic that I find very interesting and it seems to me.. everyone is in the same bag.
  - If nemutator can generate unix sockets and use those channels to refresh credentials on pod restarts (like cloudflare pald) this may work.
  - It may need a 'nemutator_secrets_agent' per node, which is definitively better than an agent per pod
  - Nemutator may need to inject a initContainer that can mount this unix socket, but I think there must be an existing mechanism somewhere within the Kubernetes brain... but where ?
