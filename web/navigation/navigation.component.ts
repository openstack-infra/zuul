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

import { OnInit, Component } from '@angular/core'
import { Router, ResolveEnd } from '@angular/router'
import { Observable } from 'rxjs/Observable'
import { filter } from 'rxjs/operators'

import ZuulService from '../zuul/zuul.service'

import RouteDescription from './description'

@Component({
  selector: 'navigation',
  template: require('./navigation.component.html')
})
export default class NavigationComponent implements OnInit {
  navbarRoutes: RouteDescription[]
  resolveEnd$: Observable<ResolveEnd>
  showNavbar = true

  private routePages = ['status', 'jobs', 'builds']

  constructor(private router: Router, private zuul: ZuulService) {}

  ngOnInit() {
    this.resolveEnd$ = this.router.events.pipe(
      filter(evt => evt instanceof ResolveEnd)
    ) as Observable<ResolveEnd>
    this.resolveEnd$.subscribe(evt => {
      this.showNavbar = (evt.url !== '/tenants.html')
      this.navbarRoutes = this.getNavbarRoutes(evt.url)
    })
  }

  getNavbarRoutes(url: string): RouteDescription[] {
    const routes = []
    for (const routePage of this.routePages) {
      const description: RouteDescription = {
        title: this.getRouteTitle(routePage),
        url: this.getRouterLink(routePage, url)
      }
      routes.push(description)
    }
    return routes
  }

  getRouteTitle(target: string): string {
    return target.charAt(0).toUpperCase() + target.slice(1)
  }

  getRouterLink(target: string, url: string): string[] {
    const htmlTarget = target + '.html'
    // NOTE: This won't work if there is a tenant name with a / in it. It would
    // be great to pull the tenant name from the paramMap- but so far I can't
    // find a way to get to the current paramMap of the current component from
    // inside of this component.
    if (url.startsWith('/t/')) {
      return ['/t', url.split('/')[2], htmlTarget]
    } else {
      return ['/' + htmlTarget]
    }
  }
}
