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

import * as url from 'url'

declare var ZUUL_API_URL: string
declare var ZUUL_BASE_HREF: string

function getAppBaseHrefFromPath () {
  const path = window.location.pathname
  if (path.includes('/t/')) {
    return path.slice(0, path.lastIndexOf('/t/') + 1)
  } else {
    return path.split('/').slice(0, -1).join('/') || '/'
  }
}

export function getAppBaseHref (): string {
  /*
   * Return a value suitable for use in
   * https://angular.io/api/common/APP_BASE_HREF
   */
  let path
  if (typeof ZUUL_BASE_HREF !== 'undefined') {
    path = ZUUL_BASE_HREF
  } else {
    // Use window.location.pathname because we're looking for a path
    // prefix, not a URL.
    path = getAppBaseHrefFromPath()
  }
  if (! path.endsWith('/')) {
    path = path + '/'
  }
  return path
}


@Injectable()
class ZuulService {
  public baseApiUrl: string
  public appBaseHref: string

  constructor() {
    this.baseApiUrl = this.getBaseApiUrl()
    this.appBaseHref = getAppBaseHref()
  }

  getBaseApiUrl (): string {
    let path
    if (typeof ZUUL_API_URL !== 'undefined') {
      path = ZUUL_API_URL
    } else {
      path = url.resolve(window.location.href, getAppBaseHrefFromPath())
    }
    if (! path.endsWith('/')) {
      path = path + '/'
    }
    return path
  }

  getSourceUrl (filename: string, tenant?: string): string {
    if (tenant) {
      // Multi-tenant deploy. This is at t/a-tenant/x.html
      return url.resolve(this.baseApiUrl, `api/tenant/${tenant}/${filename}`)
    } else {
      // Whitelabel deploy or tenants list, such as /status.html,
      // /tenants.html or /zuul/status.html or /zuul/tenants.html
      return url.resolve(this.baseApiUrl, `api/${filename}`)
    }
  }

  getWebsocketUrl (filename: string, tenant?: string): string {
    return this.getSourceUrl(filename, tenant)
      .replace(/(http)(s)?\:\/\//, 'ws$2://')
  }

}

export default ZuulService
