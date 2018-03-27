/* global ZUUL_API_URL */
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
    let tenant = extractTenant($location.url())
    if (tenant) {
      // Multi-tenant deploy. This is at t/a-tenant/x.html. api path is at
      // api/tenant/a-tenant/x, so should be at ../../api/tenant/a-tenant/x
      return `../../api/tenant/${tenant}/${filename}`
    } else {
      // Whilelabel deploy. This is at x.html. api path is at
      // api/x, so should be at api/x
      return `api/${filename}`
    }
  }
}
