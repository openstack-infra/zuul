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
import { HttpClient } from '@angular/common/http'

import ZuulService from '../zuul/zuul.service'

@Component({
  template: require('./tenants.component.html')
})
export default class TenantsComponent implements OnInit {

  tenants: Tenant[]

  constructor(private http: HttpClient, private zuul: ZuulService) {}

  ngOnInit() {
    this.tenantsFetch()
  }

  tenantsFetch(): void {
    this.http.get<Tenant[]>(this.zuul.getSourceUrl('tenants'))
      .subscribe(tenants => { this.tenants = tenants })
  }
}
