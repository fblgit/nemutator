import logging
from prometheus_api_client import PrometheusConnect

log = logging.getLogger('NEMUTATOR')


def query_prometheus(search, mode='pod', nature='cpu', prom_url=False):
    #/api/v1/query?query=avg(rate(container_cpu_usage_seconds_total%7Bnamespace%3D%22jarvis%22%2Ccontainer%3D%22cast-service%22%7D%5B5d%5D))
    prom_url = 'http://prometheus.k.nutz.site'
    if isinstance(prom_url, str):
        prom = PrometheusConnect(url=prom_url, disable_ssl=False)
    elif isinstance(prom_url, bool):
        prom = False
    else:
        prom = prom_url
    if not prom:
        log.debug(f'[QUERY-PROMETHEUS] Prometheus is Disabled or not found by K8s Service')
        return {}
    if nature not in ['cpu', 'mem']:
        log.error(f'[QUERY-PROMETHEUS] Nature {nature} not valid')
        return {}
    if mode not in ['node', 'pod', 'deployment']:
        log.error(f'[QUERY-PROMETHEUS] Mode {mode} not valid')
        return {}
    # NODE METRICS
    if mode == 'node':
        if nature == 'cpu':
            query = {
                'usage': '(1000 *  (count(node_cpu_seconds_total{instance=~"%s.+",mode="user"}) \
                - avg(sum by (mode)(irate(node_cpu_seconds_total{instance=~"%s.+",mode="idle"}[5m])))))' % (search, search),
                'total': '(1000 * (count(node_cpu_seconds_total{instance=~"%s.+",mode="user"})))' % (search)
            }
        if nature == 'mem':
            query = {
                'usage': 'node_memory_MemFree_bytes{instance=~"%s.+"}' % (search),
                'total': 'node_memory_MemTotal_bytes{instance=~"%s.+"}' % (search)
            }
        results = {
            'usage': 0,
            'total': 0
        }
        for query_mode in query.keys():
            value = prom.custom_query(query=query[query_mode])
            result = 0
            if len(value) > 0:
                value = value[0].get('value', [0, False])[-1]
                if not value:
                    log.debug(f'[QUERY-PROMETHEUS] {search} for {mode} and {nature} not found results ({query})')
                    return {}
                if nature == 'mem':
                    result = int(value)
                if nature == 'cpu':
                    result = int(round(float(value), 0))
            log.debug(f'[QUERY-PROMETHEUS] {search} {mode} {nature} results: {result}')
            results[query_mode] = result
        results['available'] = results.get('total', 0) - results.get('usage', 0)
        return results
    # DEPLOYMENT METRICS
    if mode == 'deployment':
        # max_over_time(rate(container_cpu_usage_seconds_total{container_name="ditto-asia"}[1d:1h])[1d:1h])
        # sum by (container_name)(max_over_time(rate(container_cpu_usage_seconds_total{container="ditto-asia"}[3d:3m])[3d:3m]))
        if nature == 'cpu':
            metric = 'container_cpu_usage_seconds_total'
            query = {
                'max': 'sum by (container_name)(max_over_time(rate(%s{container="%s"}[3d:3m])[3d:3m]))' % (metric, search),
                'avg': 'sum by (container_name)(avg_over_time(rate(%s{container="%s"}[3d:3m])[3d:3m]))' % (metric, search),
                'min': 'sum by (container_name)(min_over_time(rate(%s{container="%s"}[3d:3m])[3d:3m]))' % (metric, search)
            }
        elif nature == 'mem':
            metric = 'container_memory_max_usage_bytes'
            query = {
                'max': 'max(max_over_time(%s{container="%s"}[3d]))' % (metric, search),
                'avg': 'max(avg_over_time(%s{container="%s"}[3d]))' % (metric, search),
                'min': 'max(min_over_time(%s{container="%s"}[3d]))' % (metric, search)
            }
        results = {
            'max': 0,
            'avg': 0,
            'min': 0
        }
        for query_style in query.keys():
            value = prom.custom_query(query=query[query_style])
            result = 0
            if len(value) > 0:
                value = value[0].get('value', [0, False])[-1]
            if not value:
                log.debug(f'[QUERY-PROMETHEUS] {search} for {mode} and {nature} ({query_style}) not found results ({query})')
                continue
            if nature == 'cpu':
                result = round(float(value)*1000, 2)
            if nature == 'mem':
                result = round(float(value)/1024/1024, 2)
            results[query_style] = result
            log.debug(f'[QUERY-PROMETHEUS] {search} {mode} {nature} {query_style} results: {result}')
        return results
    # POD METRICS
    if mode == 'pod':
        if nature == 'cpu':
            metric = 'container_cpu_usage_seconds_total'
            query = {
                'max': 'max_over_time(rate(%s{pod="%s", container!="POD"}[3d:3m])[3d:3m])' % (metric, search),
                'avg': 'avg_over_time(rate(%s{pod="%s", container!="POD"}[3d:3m])[3d:3m])' % (metric, search),
                'min': 'min_over_time(rate(%s{pod="%s", container!="POD"}[3d:3m])[3d:3m])' % (metric, search)
            }
        elif nature == 'mem':
            metric = 'container_memory_max_usage_bytes'
            query = {
                'max': 'max(max_over_time(%s{pod="%s"}[3d]))' % (metric, search),
                'avg': 'max(avg_over_time(%s{pod="%s"}[3d]))' % (metric, search),
                'min': 'min(min_over_time(%s{pod="%s"}[3d]))' % (metric, search)
            }
        results = {
            'max': 0,
            'avg': 0,
            'min': 0
        }
        for query_style in query.keys():
            value = prom.custom_query(query=query[query_style])
            result = 0
            if len(value) > 0:
                value = value[0].get('value', [0, False])[-1]
            if not value:
                log.debug(f'[QUERY-PROMETHEUS] {search} for {mode} and {nature} ({query_style}) not found results ({query})')
                continue
            if nature == 'cpu':
                # transform to something human ready
                # style is '350'm (cpu fractions as base 100 scale per core)
                result = round(float(value)*1000, 2)
            if nature == 'mem':
                # transforms to something human ready
                # style is '350.44'mb
                result = round(float(value)/1024/1024, 2)
            results[query_style] = result
            log.debug(f'[QUERY-PROMETHEUS] {search} {mode} {nature} {query_style} results: {result}')
        return results
    return {}
