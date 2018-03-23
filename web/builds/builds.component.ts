// Copyright 2017 Red Hat
//
// Licensed under the Apache License, Version 2.0 (the "License"); you may
// not use this file except in compliance with the License. You may obtain
// a copy of the License at
//
//      http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
// WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
// License for the specific language governing permissions and limitations
// under the License.

import { Component, OnInit } from '@angular/core'
import { ActivatedRoute } from '@angular/router'
import { HttpClient, HttpParams } from '@angular/common/http'
import { Observable } from 'rxjs/Observable'
import 'rxjs/add/operator/map'

import ZuulService from '../zuul/zuul.service'
import Build from './build'


@Component({
  template: require('./builds.component.html')
})
export default class BuildsComponent implements OnInit {
  builds: Build[]
  pipeline: string
  job_name: string
  project: string
  tenant: string

  constructor(
    private http: HttpClient, private route: ActivatedRoute,
    private zuul: ZuulService
  ) {}

  ngOnInit() {

    this.tenant = this.route.snapshot.paramMap.get('tenant')

    this.pipeline = this.route.snapshot.queryParamMap.get('pipeline')
    this.job_name = this.route.snapshot.queryParamMap.get('job_name')
    this.project = this.route.snapshot.queryParamMap.get('project')

    this.buildsFetch()
  }

  buildsFetch(): void  {
    let params = new HttpParams()
    if (this.pipeline) { params = params.set('pipeline', this.pipeline) }
    if (this.job_name) { params = params.set('job_name', this.job_name) }
    if (this.project) { params = params.set('project', this.project) }

    const remoteLocation = this.zuul.getSourceUrl('builds', this.tenant)
    this.http.get<Build[]>(remoteLocation, {params: params})
      .subscribe(builds => {
        for (const build of builds) {
          /* Fix incorect url for post_failure job */
          /* TODO(mordred) Maybe let's fix this server side? */
          if (build.log_url === build.job_name) {
            build.log_url = undefined
          }
        }
        this.builds = builds
      })
  }

  getRowClass(build: Build): string {
    if (build.result === 'SUCCESS') {
      return 'success'
    } else {
      return 'warning'
    }
  }
}
