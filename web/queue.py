from redis import Redis
from rq import Queue
from rq.job import Job
from rq.exceptions import NoSuchJobError


def connection(settings):
    return Redis.from_url(settings.redis_url, socket_connect_timeout=2, socket_timeout=5)


def queue_id(job_id, generation):
    return f'comparison-{job_id}-{generation}'


def enqueue(settings, job_id, generation):
    queue = Queue(settings.queue_name, connection=connection(settings), default_timeout=settings.task_timeout)
    queue.enqueue('web.tasks.run_comparison', job_id, generation,
                  job_id=queue_id(job_id, generation), result_ttl=86400, failure_ttl=604800)


def terminal_failure(settings, job_id, generation):
    try:
        job = Job.fetch(queue_id(job_id, generation), connection=connection(settings))
        return job.get_status(refresh=True) in {'failed', 'stopped', 'canceled'}
    except NoSuchJobError:
        return True
    except Exception:
        return False
