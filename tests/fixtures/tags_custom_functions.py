def apply_tags(item, job, params):
    params['BUILD_TAGS'] = ' '.join(sorted(job.tags))
