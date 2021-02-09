import redis

class R():
    def __init__(self):
        self.redis = False

    def conn(self, cfg):
        self.redis = redis.Redis(host=cfg['redis']['ip'], db=cfg['redis']['db'], decode_responses=True)
        return self.redis

    def get_pass(self, hash_text):
        result = self.redis.get(hash_text)
        if result:
            return result
        return False

    def get_label(self, label):
        result = self.redis.get(label)
        if result:
            return result
        return False

    def get_annotation(self, annotation):
        result = self.redis.get(annotation)
        if result:
            return result
        return False

    def get_image_version(self, image):
        result = self.redis.get(image)
        if result:
            return result
        return False

    def get_selector(self, label):
        result = self.redis.get(label)
        if result:
            return result
        return False

    def get_selectors_replace(self):
        result = self.redis.get('nemu_selectors_replace_list')
        if result:
            return result.split(' ')
        return []
