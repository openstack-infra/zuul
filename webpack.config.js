module.exports = function(env) {
  return require(`./web/config/webpack.${env}.js`)
}
