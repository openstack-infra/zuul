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

import { Injectable,  EventEmitter, Output } from '@angular/core'
import { HttpClient } from '@angular/common/http'
import { Router } from '@angular/router'
import { BehaviorSubject } from 'rxjs/BehaviorSubject'

import * as url from 'url'

import Info from './info'
import InfoResponse from './infoResponse'
import RouteDescription from './description'

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

@Injectable({
  providedIn: 'root',
})
export class ZuulService {
  public baseApiUrl: string
  public appBaseHref: string
  public info: Info
  navbarRoutes: RouteDescription[]
  private routePages = ['status', 'jobs', 'builds']

  constructor(private router: Router, private http: HttpClient) {
    this.baseApiUrl = this.getBaseApiUrl()
    this.appBaseHref = getAppBaseHref()
  }

  async setTenant (tenant?: string) {
    if (!this.info) {
      const infoEndpoint = this.baseApiUrl + 'api/info'
      const infoResponse = await this.http.get<InfoResponse>(
          infoEndpoint).toPromise()
      this.info = infoResponse.info
      if (this.info.tenant && !tenant) {
        this.info.whiteLabel = true
      } else {
        this.info.whiteLabel = false
      }
    }
    if (tenant) {
      this.info.tenant = tenant
    }
    this.navbarRoutes = this.getNavbarRoutes()
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

  getSourceUrl (filename: string): string {
    const tenant = this.info.tenant
    if (this.info.whiteLabel || filename === 'tenants') {
      if (!this.info.whiteLabel) {
        // Reset selected tenant
        this.info.tenant = ''
      }
      return url.resolve(this.baseApiUrl, `api/${filename}`)
    }
    if (!tenant) {
      // No tenant selected, go to tenant list
      console.log('No tenant selected, navigate to tenants list')
      this.router.navigate(['/tenants.html'])
    }
    return url.resolve(this.baseApiUrl, `api/tenant/${tenant}/${filename}`)
  }

  getWebsocketUrl (filename: string): string {
    return this.getSourceUrl(filename)
      .replace(/(http)(s)?\:\/\//, 'ws$2://')
  }

  getNavbarRoutes(): RouteDescription[] {
    const routes = []
    for (const routePage of this.routePages) {
      const description: RouteDescription = {
        title: this.getRouteTitle(routePage),
        url: this.getRouterLink(routePage)
      }
      routes.push(description)
    }
    return routes
  }

  getRouteTitle(target: string): string {
    return target.charAt(0).toUpperCase() + target.slice(1)
  }

  getRouterLink(target: string): string[] {
    const htmlTarget = target + '.html'
    if (this.info.whiteLabel) {
      return ['/' + htmlTarget]
    } else {
      return ['/t', this.info.tenant, htmlTarget]
    }
  }

}

export default ZuulService
