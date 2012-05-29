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

import threading
from webob import Request
from paste import httpserver
from uuid import uuid1
import jenkins
import json
import urllib2  # for extending jenkins lib
import logging
import pprint

from zuul.model import Build

class JenkinsCallback(threading.Thread):
    log = logging.getLogger("zuul.JenkinsCallback")

    def __init__(self, jenkins):
        threading.Thread.__init__(self)
        self.jenkins = jenkins

    def run(self):
        httpserver.serve(self.app, host='0.0.0.0', port='8080')

    def app(self, environ, start_response):
        request = Request(environ)
        if request.path == '/jenkins_endpoint':
            self.jenkins_endpoint(request)
        start_response('200 OK', [('content-type', 'text/html')])
        return ['Zuul good.']

    def jenkins_endpoint(self, request):
        data = json.loads(request.body)
        if data:
            self.log.debug("Received data from Jenkins: \n%s" % (
                    pprint.pformat(data)))
            build = data.get('build')
            if build:
                phase = build.get('phase')
                status = build.get('status')
                url = build.get('full_url')
                number = build.get('number')
                params = build.get('parameters')
                if params:
                    uuid = params.get('UUID')
                    if (status and url and uuid and phase
                        and phase == 'COMPLETED'):
                        self.jenkins.onBuildCompleted(uuid, status, url, number)
                    if (phase and phase == 'STARTED'):
                        self.jenkins.onBuildStarted(uuid, url, number)


STOP_BUILD = 'job/%(name)s/%(number)s/stop'
CANCEL_QUEUE = 'queue/item/%(number)s/cancelQueue'
BUILD_INFO = 'job/%(name)s/%(number)s/api/json?depth=0'

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
        self.jenkins_open(urllib2.Request(self.server + STOP_BUILD%locals()))

    def cancel_queue(self, number):
        '''
        Cancel a queued build.

        @param number: Jenkins queue number for the build
        @type  number: int
        '''
        # Jenkins returns a 302 from this URL, unless Referer is not set,
        # then you get a 404.
        self.jenkins_open(urllib2.Request(self.server + CANCEL_QUEUE%locals(),
                                          headers={'Referer': self.server}))


    def get_build_info(self, name, number):
        '''
        Get information for a build.

        @param name: Name of Jenkins job
        @type  name: str
        @param number: Jenkins build number for the job
        @type  number: int
        @return: dictionary
        '''
        return json.loads(self.jenkins_open(urllib2.Request(self.server + BUILD_INFO%locals())))

class Jenkins(object):
    log = logging.getLogger("zuul.Jenkins")

    def __init__(self, config, sched):
        self.sched = sched
        self.builds = {}
        server = config.get('jenkins', 'server')
        user = config.get('jenkins', 'user')
        apikey = config.get('jenkins', 'apikey')
        self.jenkins = ExtendedJenkins(server, user, apikey)
        self.callback_thread = JenkinsCallback(self)
        self.callback_thread.start()
    
    def launch(self, job, change, dependent_changes = []):
        self.log.info("Launch job %s for change %s with dependent changes %s" % (
                job, change, dependent_changes))
        uuid = str(uuid1())
        params = dict(UUID=uuid)
        build = Build(job, uuid)
        self.builds[uuid] = build
        # We can get the started notification on another thread before this is done
        # so we add the build even before we trigger the job on Jenkins.  We should
        # be careful to clean it up if it doesn't actually kick off.
        try:
            self.jenkins.build_job(job.name, parameters=params)
        except:
            self.log.exception("Exception launching build %s for job %s for change %s:" % (
                    build, job, change))
            # Whoops.  Remove that build we added.
            del self.builds[uuid]
            raise
        return build

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
        for item in self.jenkins.get_queue_info():
            if not item.has_key('actions'):
                continue
            for action in item['actions']:
                if not action.has_key('parameters'):
                    continue
                parameters = action['parameters']
                for param in parameters:
                    if (param['name'] == 'UUID' and build.uuid == param['value']):
                        self.log.debug("Found queue item %s for build %s" % (
                                item['id'], build))
                        try:
                            self.jenkins.cancel_queue(item['id'])
                            self.log.debug("Canceled queue item %s for build %s" % (
                                    item['id'], build))
                            return
                        except:
                            self.log.exception("Exception canceling queue item %s for build %s" % (
                                    item['id'], build))

        self.log.debug("Still unable to find build %s to cancel" % build)
        if build.number:
            self.log.debug("Build %s has just started" % build)
            self.jenkins.stop_build(build.job.name, build.number)
            self.log.debug("Canceled just running build %s" % build)
        else:
            self.log.error("Build %s has not started but was not found in queue" % build)
    
    def onBuildCompleted(self, uuid, status, url, number):
        self.log.info("Build %s #%s complete, status %s" % (
                uuid, number, status))
        build = self.builds.get(uuid)
        if build:
            self.log.debug("Found build %s" % build)
            del self.builds[uuid]
            build.result = status
            build.url = url
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
        else:
            self.log.error("Unable to find build %s" % uuid)
