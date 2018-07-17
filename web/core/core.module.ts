import { ModuleWithProviders, NgModule, Optional, SkipSelf } from '@angular/core'

import { CommonModule } from '@angular/common'

import { ZuulService } from '../zuul/zuul.service'

@NgModule({
  imports:      [ CommonModule ],
  providers:    [ ZuulService ]
})
export class CoreModule {
  constructor (@Optional() @SkipSelf() parentModule: CoreModule) {
    if (parentModule) {
      throw new Error(
        'CoreModule is already loaded. Import it in the AppModule only')
    }
  }

  static forRoot(config: {}): ModuleWithProviders {
    return {
      ngModule: CoreModule,
    }
  }
}
