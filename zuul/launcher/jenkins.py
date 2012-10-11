# Copyright 2012 Hewlett-Packard Development Company, L.P.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

# So we can name this module "jenkins" and still load the "jenkins"
# system module
from __future__ import absolute_import

import json
import logging
import pprint
import threading
import time
import urllib   # for extending jenkins lib
import urllib2  # for extending jenkins lib
import urlparse
from uuid import uuid4

import jenkins
from paste import httpserver
from webob import Request

from zuul.model import Build

# The amount of time we tolerate a change in build status without
# receiving a notification
JENKINS_GRACE_TIME = 60


class JenkinsCallback(threading.Thread):
    log = logging.getLogger("zuul.JenkinsCallback")

    def __init__(self, jenkins):
        threading.Thread.__init__(self)
        self.jenkins = jenkins

    def run(self):
        httpserver.serve(self.app, host='0.0.0.0', port='8001')

    def app(self, environ, start_response):
        request = Request(environ)
        start_response('200 OK', [('content-type', 'text/html')])
        if request.path == '/jenkins_endpoint':
            self.jenkins_endpoint(request)
            return ['Zuul good.']
        elif request.path == '/status':
            try:
                ret = self.jenkins.sched.formatStatusHTML()
            except:
                self.log.exception("Exception formatting status:")
                raise
            return [ret]
        else:
            return ['Zuul good.']

    def jenkins_endpoint(self, request):
        try:
            data = json.loads(request.body)
        except:
            self.log.exception("Exception handling Jenkins notification:")
            raise  # let wsgi handler process the issue
        if data:
            self.log.debug("Received data from Jenkins: \n%s" %
                           (pprint.pformat(data)))
            build = data.get('build')
            if build:
                phase = build.get('phase')
                status = build.get('status')
                url = build.get('full_url')
                number = build.get('number')
                params = build.get('parameters')
                if params:
                    # UUID is deprecated in favor of ZUUL_UUID
                    uuid = params.get('ZUUL_UUID') or params.get('UUID')
                    if (status and url and uuid and phase and
                        phase == 'COMPLETED'):
                        self.jenkins.onBuildCompleted(uuid,
                                                      status,
                                                      url,
                                                      number)
                    if (phase and phase == 'STARTED'):
                        self.jenkins.onBuildStarted(uuid, url, number)


class JenkinsCleanup(threading.Thread):
    """ A thread that checks to see if outstanding builds have
    completed without reporting back. """
    log = logging.getLogger("zuul.JenkinsCleanup")

    def __init__(self, jenkins):
        threading.Thread.__init__(self)
        self.jenkins = jenkins
        self.wake_event = threading.Event()
        self._stopped = False

    def stop(self):
        self._stopped = True
        self.wake_event.set()

    def run(self):
        while True:
            self.wake_event.wait(180)
            if self._stopped:
                return
            try:
                self.jenkins.lookForLostBuilds()
            except:
                self.log.exception("Exception checking builds:")


STOP_BUILD = 'job/%(name)s/%(number)s/stop'
CANCEL_QUEUE = 'queue/item/%(number)s/cancelQueue'
BUILD_INFO = 'job/%(name)s/%(number)s/api/json?depth=0'
BUILD_DESCRIPTION = 'job/%(name)s/%(number)s/submitDescription'


class ExtendedJenkins(jenkins.Jenkins):
    def jenkins_open(self, req):
        '''
        Utility routine for opening an HTTP request to a Jenkins server.
        '''
        try:
            if self.auth:
                req.add_header('Authorization', self.auth)
            return urllib2.urlopen(req).read()
        except urllib2.HTTPError, e:
            print e.msg
            print e.fp.read()
            raise

    def stop_build(self, name, number):
        '''
        Stop a running Jenkins build.

        @param name: Name of Jenkins job
        @type  name: str
        @param number: Jenkins build number for the job
        @type  number: int
        '''
        request = urllib2.Request(self.server + STOP_BUILD % locals())
        self.jenkins_open(request)

    def cancel_queue(self, number):
        '''
        Cancel a queued build.

        @param number: Jenkins queue number for the build
        @type  number: int
        '''
        # Jenkins returns a 302 from this URL, unless Referer is not set,
        # then you get a 404.
        request = urllib2.Request(self.server + CANCEL_QUEUE % locals(),
                                  headers={'Referer': self.server})
        self.jenkins_open(request)

    def get_build_info(self, name, number):
        '''
        Get information for a build.

        @param name: Name of Jenkins job
        @type  name: str
        @param number: Jenkins build number for the job
        @type  number: int
        @return: dictionary
        '''
        request = urllib2.Request(self.server + BUILD_INFO % locals())
        return json.loads(self.jenkins_open(request))

    def set_build_description(self, name, number, description):
        '''
        Get information for a build.

        @param name: Name of Jenkins job
        @type  name: str
        @param number: Jenkins build number for the job
        @type  number: int
        @param description: Bulid description to set
        @type  description: str
        '''
        params = urllib.urlencode({'description': description})
        request = urllib2.Request(self.server + BUILD_DESCRIPTION % locals(),
                                  params)
        self.jenkins_open(request)


class Jenkins(object):
    log = logging.getLogger("zuul.Jenkins")
    launch_retry_timeout = 5

    def __init__(self, config, sched):
        self.sched = sched
        self.builds = {}
        server = config.get('jenkins', 'server')
        user = config.get('jenkins', 'user')
        apikey = config.get('jenkins', 'apikey')
        self.jenkins = ExtendedJenkins(server, user, apikey)
        self.callback_thread = JenkinsCallback(self)
        self.callback_thread.start()
        self.cleanup_thread = JenkinsCleanup(self)
        self.cleanup_thread.start()

    def stop(self):
        self.cleanup_thread.stop()
        self.cleanup_thread.join()

    #TODO: remove dependent_changes
    def launch(self, job, change, pipeline, dependent_changes=[]):
        self.log.info("Launch job %s for change %s with dependent changes %s" %
                      (job, change, dependent_changes))
        dependent_changes = dependent_changes[:]
        dependent_changes.reverse()
        uuid = str(uuid4().hex)
        params = dict(UUID=uuid,  # deprecated
                      ZUUL_UUID=uuid,
                      GERRIT_PROJECT=change.project.name,  # deprecated
                      ZUUL_PROJECT=change.project.name)
        params['ZUUL_PIPELINE'] = pipeline.name
        if hasattr(change, 'refspec'):
            changes_str = '^'.join(
                ['%s:%s:%s' % (c.project.name, c.branch, c.refspec)
                 for c in dependent_changes + [change]])
            params['GERRIT_BRANCH'] = change.branch  # deprecated
            params['ZUUL_BRANCH'] = change.branch
            params['GERRIT_CHANGES'] = changes_str   # deprecated
            params['ZUUL_CHANGES'] = changes_str
            params['ZUUL_REF'] = ('refs/zuul/%s/%s' %
                                  (change.branch,
                                   change.current_build_set.ref))
            params['ZUUL_COMMIT'] = change.current_build_set.commit

            zuul_changes = ' '.join(['%s,%s' % (c.number, c.patchset)
                                     for c in dependent_changes + [change]])
            params['ZUUL_CHANGE_IDS'] = zuul_changes
            params['ZUUL_CHANGE'] = str(change.number)
            params['ZUUL_PATCHSET'] = str(change.patchset)
        if hasattr(change, 'ref'):
            params['GERRIT_REFNAME'] = change.ref   # deprecated
            params['ZUUL_REFNAME'] = change.ref
            params['GERRIT_OLDREV'] = change.oldrev   # deprecated
            params['ZUUL_OLDREV'] = change.oldrev
            params['GERRIT_NEWREV'] = change.newrev   # deprecated
            params['ZUUL_NEWREV'] = change.newrev
            params['ZUUL_SHORT_OLDREV'] = change.oldrev[:7]
            params['ZUUL_SHORT_NEWREV'] = change.newrev[:7]

            params['ZUUL_REF'] = change.ref
            params['ZUUL_COMMIT'] = change.newrev

        # This is what we should be heading toward for parameters:

        # required:
        # ZUUL_UUID
        # ZUUL_REF (/refs/zuul/..., /refs/tags/foo, master)
        # ZUUL_COMMIT

        # optional:
        # ZUUL_PROJECT
        # ZUUL_PIPELINE

        # optional (changes only):
        # ZUUL_BRANCH
        # ZUUL_CHANGE
        # ZUUL_CHANGE_IDS
        # ZUUL_PATCHSET

        # optional (ref updated only):
        # ZUUL_OLDREV
        # ZUUL_NEWREV
        # ZUUL_SHORT_NEWREV
        # ZUUL_SHORT_OLDREV

        if callable(job.parameter_function):
            job.parameter_function(change, params)
            self.log.debug("Custom parameter function used for job %s, "
                           "change: %s, params: %s" % (job, change, params))

        build = Build(job, uuid)
        # We can get the started notification on another thread before
        # this is done so we add the build even before we trigger the
        # job on Jenkins.
        self.builds[uuid] = build
        # Sometimes Jenkins may erroneously respond with a 404.  Handle
        # that by retrying for 30 seconds.
        launched = False
        errored = False
        for count in range(6):
            try:
                self.jenkins.build_job(job.name, parameters=params)
                launched = True
                break
            except:
                errored = True
                self.log.exception("Exception launching build %s for "
                                   "job %s for change %s (will retry):" %
                                   (build, job, change))
                time.sleep(self.launch_retry_timeout)

        if errored:
            if launched:
                self.log.error("Finally able to launch %s" % build)
            else:
                self.log.error("Unable to launch %s, even after retrying, "
                               "declaring lost" % build)
                # To keep the queue moving, declare this as a lost build
                # so that the change will get dropped.
                t = threading.Thread(target=self.declareBuildLost,
                                     args=(build,))
                t.start()
        return build

    def declareBuildLost(self, build):
        # Call this from a new thread to invoke onBuildCompleted from
        # a thread that has the queue lock.
        self.onBuildCompleted(build.uuid, 'LOST', None, None)

    def findBuildInQueue(self, build):
        for item in self.jenkins.get_queue_info():
            if 'actions' not in item:
                continue
            for action in item['actions']:
                if 'parameters' not in action:
                    continue
                parameters = action['parameters']
                for param in parameters:
                    # UUID is deprecated in favor of ZUUL_UUID
                    if ((param['name'] in ['ZUUL_UUID', 'UUID'])
                        and build.uuid == param['value']):
                        return item
        return False

    def cancel(self, build):
        self.log.info("Cancel build %s for job %s" % (build, build.job))
        if build.number:
            self.log.debug("Build %s has already started" % build)
            self.jenkins.stop_build(build.job.name, build.number)
            self.log.debug("Canceled running build %s" % build)
            return
        else:
            self.log.debug("Build %s has not started yet" % build)

        self.log.debug("Looking for build %s in queue" % build)
        item = self.findBuildInQueue(build)
        if item:
            self.log.debug("Found queue item %s for build %s" %
                           (item['id'], build))
            try:
                self.jenkins.cancel_queue(item['id'])
                self.log.debug("Canceled queue item %s for build %s" %
                               (item['id'], build))
                return
            except:
                self.log.exception("Exception canceling queue item %s "
                                   "for build %s" % (item['id'], build))

        self.log.debug("Still unable to find build %s to cancel" % build)
        if build.number:
            self.log.debug("Build %s has just started" % build)
            self.jenkins.stop_build(build.job.name, build.number)
            self.log.debug("Canceled just running build %s" % build)
        else:
            self.log.error("Build %s has not started but "
                           "was not found in queue" % build)

    def getBestBuildURL(self, url):
        try:
            test_url = urlparse.urljoin(url, 'testReport')
            self.jenkins.jenkins_open(urllib2.Request(test_url))
            return test_url
        except:
            pass
        try:
            console_url = urlparse.urljoin(url, 'consoleFull')
            self.jenkins.jenkins_open(urllib2.Request(console_url))
            return console_url
        except:
            pass
        return url

    def setBuildDescription(self, build, description):
        if not build.number:
            return
        try:
            self.jenkins.set_build_description(build.job.name,
                                               build.number,
                                               description)
        except:
            self.log.exception("Exception setting build description for %s" %
                               build)

    def onBuildCompleted(self, uuid, status, url, number):
        self.log.info("Build %s #%s complete, status %s" %
                      (uuid, number, status))
        build = self.builds.get(uuid)
        if build:
            self.log.debug("Found build %s" % build)
            del self.builds[uuid]
            if url:
                build.base_url = url
                url = self.getBestBuildURL(url)
                build.url = url
            build.result = status
            build.number = number
            self.sched.onBuildCompleted(build)
        else:
            self.log.error("Unable to find build %s" % uuid)

    def onBuildStarted(self, uuid, url, number):
        self.log.info("Build %s #%s started, url: %s" % (uuid, number, url))
        build = self.builds.get(uuid)
        if build:
            self.log.debug("Found build %s" % build)
            build.url = url
            build.number = number
            self.sched.onBuildStarted(build)
        else:
            self.log.error("Unable to find build %s" % uuid)

    def lookForLostBuilds(self):
        self.log.debug("Looking for lost builds")
        lostbuilds = []
        for build in self.builds.values():
            if build.result:
                # The build has finished, it will be removed
                continue
            if build.number:
                # The build has started; see if it has finished
                try:
                    info = self.jenkins.get_build_info(build.job.name,
                                                       build.number)
                    if hasattr(build, '_jenkins_missing_build_info'):
                        del build._jenkins_missing_build_info
                except:
                    self.log.exception("Exception getting info for %s" % build)
                    # We can't look it up in jenkins.  That could be transient.
                    # If it keeps up, assume it's permanent.
                    if hasattr(build, '_jenkins_missing_build_info'):
                        missing_time = build._jenkins_missing_build_info
                        if time.time() - missing_time > JENKINS_GRACE_TIME:
                            self.log.debug("Lost build %s because "
                                           "it has started but "
                                           "the build URL is not working" %
                                           build)
                            lostbuilds.append(build)
                    else:
                        build._jenkins_missing_build_info = time.time()
                    continue

                if not info:
                    self.log.debug("Lost build %s because "
                                   "it started but "
                                   "info can not be retreived" % build)
                    lostbuilds.append(build)
                    continue
                if info['building']:
                    # It has not finished.
                    continue
                if info['duration'] == 0:
                    # Possible jenkins bug -- not building, but no duration
                    self.log.debug("Possible jenkins bug with build %s: "
                                   "not building, but no duration is set "
                                   "Build info %s:" % (build,
                                                       pprint.pformat(info)))
                    continue
                finish_time = (info['timestamp'] + info['duration']) / 1000
                if time.time() - finish_time > JENKINS_GRACE_TIME:
                    self.log.debug("Lost build %s because "
                                   "it finished more than 5 minutes ago.  "
                                   "Build info %s:" % (build,
                                                       pprint.pformat(info)))
                    lostbuilds.append(build)
                    continue
                # Give it more time
            else:
                # The build has not started
                if time.time() - build.launch_time < JENKINS_GRACE_TIME:
                    # It just started, give it a bit
                    continue
                info = self.findBuildInQueue(build)
                if info:
                    # It's in the queue.  All good.
                    continue
                if build.number:
                    # We just got notified it started
                    continue
                # It may have just started.  If we keep ending up here,
                # assume the worst.
                if hasattr(build, '_jenkins_missing_from_queue'):
                    missing_time = build._jenkins_missing_from_queue
                    if time.time() - missing_time > JENKINS_GRACE_TIME:
                        self.log.debug("Lost build %s because "
                                       "it has not started and "
                                       "is not in the queue" % build)
                        lostbuilds.append(build)
                        continue
                else:
                    build._jenkins_missing_from_queue = time.time()

        for build in lostbuilds:
            self.log.error("Declaring %s lost" % build)
            self.onBuildCompleted(build.uuid, 'LOST', None, None)
