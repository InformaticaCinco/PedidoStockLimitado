import json
import logging
from datetime import datetime, timezone

log = logging.getLogger('cargas')


def event(name, **fields):
    log.info(json.dumps(dict(timestamp=datetime.now(timezone.utc).isoformat(),
                            servicio='cargas-python', evento=name, **fields), ensure_ascii=True))
