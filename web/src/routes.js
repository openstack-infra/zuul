// Copyright 2018 Red Hat, Inc
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

import StatusPage from './pages/Status'
import ChangeStatusPage from './pages/ChangeStatus'
import ProjectPage from './pages/Project'
import ProjectsPage from './pages/Projects'
import JobPage from './pages/Job'
import JobsPage from './pages/Jobs'
import LabelsPage from './pages/Labels'
import NodesPage from './pages/Nodes'
import BuildPage from './pages/Build'
import BuildsPage from './pages/Builds'
import BuildsetsPage from './pages/Buildsets'
import ConfigErrorsPage from './pages/ConfigErrors'
import TenantsPage from './pages/Tenants'
import StreamPage from './pages/Stream'

// The Route object are created in the App component.
// Object with a title are created in the menu.
// Object with globalRoute are not tenant scoped.
// Remember to update the api getHomepageUrl subDir list for route with params
const routes = () => [
  {
    title: 'Status',
    to: '/status',
    component: StatusPage
  },
  {
    title: 'Projects',
    to: '/projects',
    component: ProjectsPage
  },
  {
    title: 'Jobs',
    to: '/jobs',
    component: JobsPage
  },
  {
    title: 'Labels',
    to: '/labels',
    component: LabelsPage
  },
  {
    title: 'Nodes',
    to: '/nodes',
    component: NodesPage
  },
  {
    title: 'Builds',
    to: '/builds',
    component: BuildsPage
  },
  {
    title: 'Buildsets',
    to: '/buildsets',
    component: BuildsetsPage
  },
  {
    to: '/status/change/:changeId',
    component: ChangeStatusPage
  },
  {
    to: '/stream/:buildId',
    component: StreamPage
  },
  {
    to: '/project/:projectName*',
    component: ProjectPage
  },
  {
    to: '/job/:jobName',
    component: JobPage
  },
  {
    to: '/build/:buildId',
    component: BuildPage
  },
  {
    to: '/config-errors',
    component: ConfigErrorsPage,
  },
  {
    to: '/tenants',
    component: TenantsPage,
    globalRoute: true
  }
]

export { routes }
