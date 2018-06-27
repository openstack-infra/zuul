// Copyright 2018 Red Hat, Inc.
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

import { Component, OnInit, OnDestroy } from '@angular/core'
import { ActivatedRoute } from '@angular/router'

import ZuulService from '../zuul/zuul.service'
import zuulStart from './zuulStart'

interface ZuulStatusOption {
  enabled: boolean
}

interface ZuulStatus {
  options: ZuulStatusOption
}

@Component({
  template: require('./status.component.html')
})
export default class StatusComponent implements OnInit, OnDestroy {
  tenant: string
  app: ZuulStatus

  constructor(private route: ActivatedRoute, private zuul: ZuulService) {}

  ngOnInit() {
    if (this.app) {
      this.app.options.enabled = true
    } else {
      this.app = zuulStart(
        jQuery, this.route.snapshot.paramMap.get('tenant'), this.zuul)
    }
  }

  ngOnDestroy() {
    this.app.options.enabled = false
  }
}
