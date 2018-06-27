const path = require('path');
const webpack = require('webpack');
const Merge = require('webpack-merge');
const CommonConfig = require('./webpack.common.js');

module.exports = Merge(CommonConfig, {
  mode: 'development',
  // Enable Hot Module Replacement for devServer
  devServer: {
    hot: true,
    contentBase: path.resolve(__dirname, './zuul/web/static'),
    publicPath: '/'
  },
  module: {
    rules: [
      {
        enforce: 'pre',
        test: /\.js$/,
        use: [
          'babel-loader',
          'eslint-loader'
        ],
        exclude: /node_modules/,
      }
    ]
  },
  plugins: [
    new webpack.HotModuleReplacementPlugin(),
    // We only need to bundle the demo files when we're running locally
    new webpack.ProvidePlugin({
        DemoStatusBasic: './status-basic.json',
        DemoStatusOpenStack: './status-openstack.json',
        DemoStatusTree: './status-tree.json'
    }),
  ]
})
