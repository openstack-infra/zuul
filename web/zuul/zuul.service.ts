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

import { Injectable } from '@angular/core'
import { ActivatedRoute } from '@angular/router'

import { getBaseHrefFromPath } from '../util'
import * as url from 'url'

declare var ZUUL_API_URL: string
declare var ZUUL_BASE_HREF: string

@Injectable()
class ZuulService {
  private baseHref: string

  constructor() {
    if (typeof ZUUL_API_URL !== 'undefined') {
      this.baseHref = ZUUL_API_URL
    } else {
      this.baseHref = getBaseHrefFromPath(window.location.pathname)
    }
    if (this.baseHref.endsWith('/')) {
      this.baseHref = this.baseHref.slice(0, 1)
    }
  }

  getSourceUrl (filename: string, tenant?: string): string {
    if (tenant) {
      // Multi-tenant deploy. This is at t/a-tenant/x.html
      return `${this.baseHref}/api/tenant/${tenant}/${filename}`
    } else {
      // Whitelabel deploy or tenants list, such as /status.html,
      // /tenants.html or /zuul/status.html or /zuul/tenants.html
      return `${this.baseHref}/api/${filename}`
    }
  }

  getWebsocketUrl (filename: string, tenant?: string): string {
    let apiBase: string
    if (typeof ZUUL_API_URL !== 'undefined') {
      apiBase = ZUUL_API_URL
    } else {
      apiBase = window.location.href
    }

    return url
      .resolve(apiBase, this.getSourceUrl(filename, tenant))
      .replace(/(http)(s)?\:\/\//, 'ws$2://')
  }

  getBaseHrefFromPath (path: string) {
    if (path.includes('/t/')) {
      return path.slice(0, path.lastIndexOf('/t/') + 1)
    } else {
      return path.split('/').slice(0, -1).join('/') + '/'
    }
  }

  getBaseHref (): string {
    if (typeof ZUUL_BASE_HREF !== 'undefined') {
      return ZUUL_BASE_HREF
    } else {
      return this.getBaseHrefFromPath(window.location.pathname)
    }
  }
}

export default ZuulService
