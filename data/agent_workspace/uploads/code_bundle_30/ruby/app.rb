def titleize(text)
  text.split.map(&:capitalize).join(' ')
end

puts titleize('ruby sample app')
