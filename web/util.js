/* global URL, ZUUL_API_URL */
// @licstart  The following is the entire license notice for the
// JavaScript code in this page.
//
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
//
// @licend  The above is the entire license notice
// for the JavaScript code in this page.

// TODO(mordred) This is a temporary hack until we're on @angular/router
function extractTenant (url) {
  if (url.includes('/t/')) {
    // This is a multi-tenant deploy, find the tenant
    const tenantStart = url.lastIndexOf('/t/') + 3
    const tenantEnd = url.indexOf('/', tenantStart)
    return url.slice(tenantStart, tenantEnd)
  } else {
    return null
  }
}

// TODO(mordred) This should be encapsulated in an Angular Service singleton
// that fetches the other things from the info endpoint.
export function getSourceUrl (filename, $location) {
  if (typeof ZUUL_API_URL !== 'undefined') {
    return `${ZUUL_API_URL}/api/${filename}`
  } else {
    const currentUrl = new URL(window.location)
    const tenant = extractTenant(currentUrl.href)
    const baseHref = getBaseHrefFromPath(currentUrl.pathname)
    if (tenant) {
      // Multi-tenant deploy. This is at t/a-tenant/x.html
      return `${baseHref}api/tenant/${tenant}/${filename}`
    } else {
      // Whitelabel deploy or tenants list, such as /status.html, /tenants.html
      // or /zuul/status.html or /zuul/tenants.html
      return `${baseHref}api/${filename}`
    }
  }
}

function getBaseHrefFromPath (path) {
  if (path.includes('/t/')) {
    return path.slice(0, path.lastIndexOf('/t/') + 1)
  } else {
    return path.split('/').slice(0, -1).join('/') + '/'
  }
}
